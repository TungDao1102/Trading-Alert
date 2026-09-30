"""History-depth backfill CLI (Phase 13, plan 13-07; D-04, D-10, D-26, F-906).

`python -m src.data.backfill_cli` refreshes versioned symbol metadata first,
then backfills trade and mark klines at the decided depth over each symbol's
real trading life. No network: a plain fake adapter serves generated full-day
bars, and every published file lands in `tmp_path`.

Every CLI test passes explicit temporary `--manifest` and `--collect-list`
paths, never the repository defaults: plan 13-12 freezes the real manifest and
plan 13-13 changes the default collect list.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from binance_sdk_derivatives_trading_usds_futures import BadRequestError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from src.adapters.binance_usdm import Kline, MarkKline, SymbolFilters
from src.data.backfill import LIVE_5
from src.db.models import Base, SymbolMetadata

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
HOUR_MS = 3_600_000
MINUTE_MS = 60_000
DAY_MS = 86_400_000
_INTERVAL_MS = {"1m": MINUTE_MS, "1h": HOUR_MS, "4h": 4 * HOUR_MS}

RUN_NOW = datetime(2026, 9, 30, 1, 0, tzinfo=UTC)


def _ms(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    """Integer epoch milliseconds for a UTC wall-clock instant."""
    delta = datetime(year, month, day, hour, minute, tzinfo=UTC) - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1000


def _dt(ms: int) -> datetime:
    return _EPOCH + timedelta(milliseconds=ms)


def _clock(minutes: int = 0) -> Callable[[], datetime]:
    fixed = RUN_NOW + timedelta(minutes=minutes)
    return lambda: fixed


def _filters(
    symbol: str,
    *,
    status: str = "TRADING",
    contract_type: str = "PERPETUAL",
    onboard: datetime | None = datetime(2019, 9, 8, tzinfo=UTC),
    delivery_ms: int | None = None,
) -> SymbolFilters:
    return SymbolFilters(
        symbol=symbol,
        contract_type=contract_type,
        status=status,
        onboard_time_utc=onboard,
        price_tick_size=Decimal("0.10"),
        quantity_step_size=Decimal("0.001"),
        min_quantity=Decimal("0.001"),
        max_quantity=Decimal("1000"),
        min_notional=Decimal("50"),
        base_asset=symbol[:-4],
        quote_asset="USDT",
        margin_asset="USDT",
        notional_constraints_json='{"filterType":"MIN_NOTIONAL","notional":"50"}',
        order_capabilities_json='{"order_types":["LIMIT","MARKET"]}',
        position_mode_snapshot_json='{"pricePrecision":2,"quantityPrecision":3}',
        delivery_date_ms=delivery_ms,
    )


class FakeAdapter:
    """Serves generated bars like the exchange and records every call.

    Bars exist for `open_ms in [first_ms(symbol), data_end_ms)`. From
    `flat_from_ms[symbol]` on they are the synthetic flat zero-volume bars the
    exchange keeps serving after a contract's delivery (research Pitfall 1).
    `fail_on_kline_call` raises on that (1-based) trade klines call, to
    simulate a killed run. Bars whose UTC day starts at a `skip_days_ms`
    instant are never served (a hole in the exchange history).
    """

    def __init__(
        self,
        filters: Sequence[SymbolFilters],
        *,
        session: Session | None = None,
        first_ms: dict[str, int] | None = None,
        flat_from_ms: dict[str, int] | None = None,
        data_end_ms: int | None = None,
        fail_on_kline_call: int | None = None,
        skip_days_ms: Sequence[int] = (),
        invalid_symbols: Sequence[str] = (),
        invalid_mark_symbols: Sequence[str] = (),
        funding_fail_symbols: Sequence[str] = (),
    ) -> None:
        self._filters = list(filters)
        self._invalid_symbols = frozenset(invalid_symbols)
        self._invalid_mark_symbols = frozenset(invalid_mark_symbols)
        self._funding_fail_symbols = frozenset(funding_fail_symbols)
        self.funding_calls: list[tuple[str | None, int | None, int | None]] = []
        self._skip_days_ms = frozenset(skip_days_ms)
        self._session = session
        self._first_ms = first_ms or {}
        self._flat_from_ms = flat_from_ms or {}
        self._data_end_ms = data_end_ms if data_end_ms is not None else _ms(2026, 9, 30, 1)
        self._fail_on_kline_call = fail_on_kline_call
        self.calls: list[str] = []
        self.kline_requests: list[tuple[str, str, int]] = []
        self.mark_requests: list[tuple[str, str, int]] = []
        self.metadata_rows_at_first_klines: int | None = None
        self._kline_call_count = 0

    def _opens(self, symbol: str, interval: str, start_ms: int, limit: int) -> list[int]:
        step = _INTERVAL_MS[interval]
        begin = max(start_ms, self._first_ms.get(symbol, 0))
        first_open = -(-begin // step) * step
        out: list[int] = []
        open_ms = first_open
        while len(out) < limit and open_ms < self._data_end_ms:
            if open_ms - open_ms % DAY_MS not in self._skip_days_ms:
                out.append(open_ms)
            open_ms += step
        return out

    async def exchange_info(self) -> list[SymbolFilters]:
        self.calls.append("exchange_info")
        return list(self._filters)

    async def klines(
        self,
        *,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        self.calls.append("klines")
        if symbol in self._invalid_symbols:
            raise BadRequestError(error_message="Invalid symbol.", status_code=-1121)
        self._kline_call_count += 1
        if self.metadata_rows_at_first_klines is None and self._session is not None:
            self.metadata_rows_at_first_klines = int(
                self._session.execute(
                    select(func.count()).select_from(SymbolMetadata)
                ).scalar_one()
            )
        if (
            self._fail_on_kline_call is not None
            and self._kline_call_count == self._fail_on_kline_call
        ):
            raise RuntimeError("simulated kill")
        step = _INTERVAL_MS[interval]
        self.kline_requests.append((symbol, interval, start_ms or 0))
        flat_from = self._flat_from_ms.get(symbol)
        rows: list[Kline] = []
        for open_ms in self._opens(symbol, interval, start_ms or 0, limit):
            flat = flat_from is not None and open_ms >= flat_from
            price = Decimal("100.00")
            rows.append(
                Kline(
                    symbol=symbol,
                    interval=interval,
                    open_time_utc=_dt(open_ms),
                    close_time_utc=_dt(open_ms + step - 1),
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=Decimal("0") if flat else Decimal("1.0"),
                    quote_volume=Decimal("0") if flat else Decimal("100.00"),
                    trade_count=0 if flat else 10,
                )
            )
        return rows

    async def mark_klines(
        self,
        *,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[MarkKline]:
        self.calls.append("mark_klines")
        if symbol in self._invalid_mark_symbols:
            raise BadRequestError(error_message="Invalid symbol.", status_code=-1121)
        step = _INTERVAL_MS[interval]
        self.mark_requests.append((symbol, interval, start_ms or 0))
        rows: list[MarkKline] = []
        for open_ms in self._opens(symbol, interval, start_ms or 0, limit):
            price = Decimal("100.00000000")
            rows.append(
                MarkKline(
                    symbol=symbol,
                    interval=interval,
                    open_time_utc=_dt(open_ms),
                    close_time_utc=_dt(open_ms + step - 1),
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    price_tick_count=60,
                )
            )
        return rows


    async def funding_rate(
        self,
        symbol: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1000,
    ) -> list[Any]:
        self.funding_calls.append((symbol, start_ms, end_ms))
        if symbol in self._funding_fail_symbols:
            raise RuntimeError("simulated funding failure")
        return []


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    """File-backed SQLite (so `main` can be pointed at it by URL) with the schema."""
    engine = create_engine(f"sqlite:///{tmp_path / 'backfill.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Any:
    s = session_factory()
    try:
        yield s
    finally:
        s.close()


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'backfill.db'}"


def _write_manifest(
    path: Path,
    *,
    status: str = "DRAFT",
    selection_date: str = "",
    symbols: Sequence[str] = (),
) -> Path:
    listed = ", ".join(f'"{s}"' for s in symbols)
    path.write_text(
        'schema = "research-universe/1"\n'
        f'status = "{status}"\n'
        'universe_id = "research-universe-v1"\n'
        f'selection_date = "{selection_date}"\n'
        f"symbols = [{listed}]\n",
        encoding="utf-8",
    )
    return path


def _write_collect_list(path: Path, extra: Sequence[str] = ()) -> Path:
    symbols = sorted({*LIVE_5, *extra})
    listed = ", ".join(f'"{s}"' for s in symbols)
    path.write_text(
        'schema = "collect-list/1"\n'
        'list_id = "test-collect-list"\n'
        'chosen_on = "2026-09-01"\n'
        'selection_rule = "test fixture"\n'
        "top_n = 15\n"
        f"symbols = [{listed}]\n",
        encoding="utf-8",
    )
    return path


def _day_dirs(raw_root: Path, interval: str, symbol: str, *, sub: str = "") -> list[str]:
    base = raw_root / sub / f"interval={interval}" / f"symbol={symbol}"
    if not base.exists():
        return []
    return sorted(p.name.removeprefix("date=") for p in base.glob("date=*"))


def _config(tmp_path: Path, **overrides: Any) -> Any:
    from src.data.backfill_cli import BackfillRunConfig

    params: dict[str, Any] = {
        "symbols": ["BTCUSDT"],
        "intervals": ["1h"],
        "datasets": ["trade"],
        "depth_months": {"1h": 24},
        "htf_start_date": None,
        "raw_root": tmp_path / "raw",
        "cursor_root": tmp_path / "cursors",
        "pace_seconds": 0.0,
        "dry_run": False,
        "funding": False,
    }
    params.update(overrides)
    return BackfillRunConfig(**params)


# --------------------------------------------------------------------------- #
# Task 1 - tracer: exchangeInfo -> metadata rows -> published 1h day files.
# --------------------------------------------------------------------------- #


async def test_cli_refreshes_metadata_before_backfill(
    tmp_path: Path, session: Session
) -> None:
    from src.data.backfill_cli import run_backfill

    adapter = FakeAdapter([_filters("BTCUSDT")], session=session)
    report = await run_backfill(
        _config(tmp_path), adapter=adapter, session=session, clock=_clock()
    )

    # exchange_info is the first adapter call and the metadata row is already
    # durable when the first klines request is made.
    assert adapter.calls[0] == "exchange_info"
    assert adapter.metadata_rows_at_first_klines == 1
    assert report.metadata_rows == 1

    window = next(
        w for w in report.windows if (w.dataset, w.symbol, w.interval) == ("trade", "BTCUSDT", "1h")
    )
    assert window.start_ms == _ms(2024, 9, 30)
    assert window.end_ms == _ms(2026, 9, 30)
    assert window.cause == "FULL_DEPTH"
    assert window.terminal is False
    assert report.run_date == date(2026, 9, 30)

    days = _day_dirs(tmp_path / "raw", "1h", "BTCUSDT")
    assert len(days) == 730
    assert days[0] == "2024-09-30"
    assert days[-1] == "2026-09-29"
    assert "2026-09-30" not in days


def test_cli_prints_depth_in_run_header(
    tmp_path: Path,
    session_factory: sessionmaker[Session],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.data import backfill_cli

    adapter = FakeAdapter([_filters("BTCUSDT")])
    monkeypatch.setattr(backfill_cli, "BinanceUsdmAdapter", lambda: adapter)
    monkeypatch.setattr(backfill_cli, "_utc_now", _clock())
    manifest = _write_manifest(tmp_path / "manifest.toml")
    collect = _write_collect_list(tmp_path / "collect.toml")

    rc = backfill_cli.main(
        [
            "--symbols", "BTCUSDT",
            "--intervals", "1h",
            "--datasets", "trade",
            "--database-url", _sqlite_url(tmp_path),
            "--raw-root", str(tmp_path / "raw"),
            "--cursor-root", str(tmp_path / "cursors"),
            "--manifest", str(manifest),
            "--collect-list", str(collect),
            "--pace-seconds", "0",
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "depth 1h=24 months" in out
    assert "run_date 2026-09-30" in out
    assert adapter.calls[0] == "exchange_info"
    assert _day_dirs(tmp_path / "raw", "1h", "BTCUSDT")


@pytest.mark.parametrize(
    "bad_args",
    [["--datasets", "funding"], ["--intervals", "5m"], ["--datasets", "trade", "bogus"]],
)
def test_unknown_dataset_or_interval_exits_2_without_adapter_call(
    tmp_path: Path,
    bad_args: list[str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.data import backfill_cli

    def _boom() -> Any:
        raise AssertionError("adapter must not be constructed on a usage error")

    monkeypatch.setattr(backfill_cli, "BinanceUsdmAdapter", _boom)
    manifest = _write_manifest(tmp_path / "manifest.toml")
    collect = _write_collect_list(tmp_path / "collect.toml")

    rc = backfill_cli.main(
        [
            "--symbols", "BTCUSDT",
            "--manifest", str(manifest),
            "--collect-list", str(collect),
            *bad_args,
        ]
    )

    assert rc == 2
    assert "expected one of" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Task 2 - per-symbol windows: onboard floor, delivery cap, frozen start,
# mark bounds, resume and dry-run.
# --------------------------------------------------------------------------- #

FAR_FUTURE_DELIVERY_MS = 4_133_404_800_000  # the TRADING perpetual sentinel


def _plan(
    filters: dict[str, SymbolFilters],
    *,
    intervals: Sequence[str] = ("1h",),
    datasets: Sequence[str] = ("trade",),
    depth_months: dict[str, int] | None = None,
    htf_start_date: date | None = None,
) -> Any:
    from src.data.backfill_cli import plan_windows

    return plan_windows(
        filters,
        symbols=list(filters),
        intervals=intervals,
        datasets=datasets,
        run_date=date(2026, 9, 30),
        now_ms=int((RUN_NOW - _EPOCH) / timedelta(milliseconds=1)),
        depth_months=depth_months or {"1m": 12, "1h": 24, "4h": 24},
        htf_start_date=htf_start_date,
    )


def test_onboard_limited_window_starts_at_onboard_time() -> None:
    windows = _plan(
        {"NEWUSDT": _filters("NEWUSDT", onboard=datetime(2025, 3, 10, 7, tzinfo=UTC))}
    )

    (window,) = windows
    assert window.start_ms == _ms(2025, 3, 10, 7)
    assert window.end_ms == _ms(2026, 9, 30)
    assert window.cause == "ONBOARD_LIMITED"
    assert window.terminal is False


def test_trading_symbol_with_far_future_delivery_is_not_capped() -> None:
    windows = _plan({"BTCUSDT": _filters("BTCUSDT", delivery_ms=FAR_FUTURE_DELIVERY_MS)})

    (window,) = windows
    assert window.end_ms == _ms(2026, 9, 30)
    assert window.terminal is False
    assert window.cause == "FULL_DEPTH"


def test_non_trading_symbol_without_delivery_date_gets_no_window() -> None:
    windows = _plan(
        {"OLDUSDT": _filters("OLDUSDT", status="SETTLING", delivery_ms=None)}
    )

    (window,) = windows
    assert window.cause == "DELIVERY_UNKNOWN"
    assert window.has_window is False


def test_pending_symbol_onboarding_after_run_end_is_not_listed_in_range() -> None:
    windows = _plan(
        {
            "SOONUSDT": _filters(
                "SOONUSDT",
                status="PENDING_TRADING",
                onboard=datetime(2026, 10, 5, tzinfo=UTC),
                delivery_ms=FAR_FUTURE_DELIVERY_MS,
            )
        }
    )

    (window,) = windows
    assert window.cause == "NOT_LISTED_IN_RANGE"
    assert window.has_window is False


def test_mark_windows_match_trade_windows() -> None:
    filters = {
        "BTCUSDT": _filters("BTCUSDT"),
        "NEWUSDT": _filters("NEWUSDT", onboard=datetime(2025, 3, 10, 7, tzinfo=UTC)),
        "FTTUSDT": _filters(
            "FTTUSDT", status="SETTLING", delivery_ms=_ms(2026, 8, 10, 8)
        ),
    }

    windows = _plan(filters, intervals=("1h", "4h"), datasets=("trade", "mark"))

    def key(w: Any) -> tuple[str, str, int | None, int | None, bool, str]:
        return (w.symbol, w.interval, w.start_ms, w.end_ms, w.terminal, w.cause)

    trade = sorted(key(w) for w in windows if w.dataset == "trade")
    mark = sorted(key(w) for w in windows if w.dataset == "mark")
    assert trade == mark
    assert len(trade) == 6


async def test_delivered_symbol_never_publishes_post_delivery_bars(
    tmp_path: Path, session: Session
) -> None:
    import polars as pl
    from src.data.backfill_cli import run_backfill

    delivery_ms = _ms(2026, 8, 10, 8)
    fixture = _filters("FTTUSDT", status="SETTLING", delivery_ms=delivery_ms)
    # The exchange keeps serving flat zero-volume bars after delivery, all the
    # way to "now" (research Pitfall 1).
    adapter = FakeAdapter([fixture], session=session, flat_from_ms={"FTTUSDT": delivery_ms})

    report = await run_backfill(
        _config(tmp_path, symbols=["FTTUSDT"], depth_months={"1h": 2}),
        adapter=adapter,
        session=session,
        clock=_clock(),
    )

    (window,) = [w for w in report.windows if w.has_window]
    assert window.terminal is True
    assert window.cause == "DELISTED_CAPPED"
    assert window.end_ms == delivery_ms
    days = _day_dirs(tmp_path / "raw", "1h", "FTTUSDT")
    assert days[0] == "2026-07-30"
    # No date directory after the delivery day exists; the delivery day itself
    # is published (terminal) with its eight pre-delivery bars.
    assert days[-1] == "2026-08-10"
    assert not [d for d in days if d > "2026-08-10"]
    delivery_day = (
        tmp_path / "raw" / "interval=1h" / "symbol=FTTUSDT" / "date=2026-08-10" / "part.parquet"
    )
    assert pl.read_parquet(delivery_day).height == 8


async def test_symbols_without_window_are_listed_and_never_fetched(
    tmp_path: Path, session: Session
) -> None:
    from src.data.backfill_cli import run_backfill

    adapter = FakeAdapter(
        [
            _filters("OLDUSDT", status="SETTLING", delivery_ms=None),
            _filters(
                "SOONUSDT",
                status="PENDING_TRADING",
                onboard=datetime(2026, 10, 5, tzinfo=UTC),
                delivery_ms=FAR_FUTURE_DELIVERY_MS,
            ),
        ],
        session=session,
    )
    lines: list[str] = []

    report = await run_backfill(
        _config(tmp_path, symbols=["OLDUSDT", "SOONUSDT"], depth_months={"1h": 1}),
        adapter=adapter,
        session=session,
        clock=_clock(),
        emit=lines.append,
    )

    assert adapter.kline_requests == []
    assert {w.cause for w in report.windows} == {"DELIVERY_UNKNOWN", "NOT_LISTED_IN_RANGE"}
    text = "\n".join(lines)
    assert "OLDUSDT" in text and "DELIVERY_UNKNOWN" in text
    assert "SOONUSDT" in text and "NOT_LISTED_IN_RANGE" in text


async def test_mark_dataset_uses_trade_bounds_and_its_own_root(
    tmp_path: Path, session: Session
) -> None:
    from src.data.backfill_cli import run_backfill

    adapter = FakeAdapter(
        [_filters("NEWUSDT", onboard=datetime(2026, 9, 10, 7, tzinfo=UTC))],
        session=session,
        first_ms={"NEWUSDT": _ms(2026, 9, 10, 7)},
    )

    await run_backfill(
        _config(
            tmp_path,
            symbols=["NEWUSDT"],
            datasets=["trade", "mark"],
            depth_months={"1h": 2},
        ),
        adapter=adapter,
        session=session,
        clock=_clock(),
    )

    # Neither dataset is requested before onboard; roots are disjoint.
    assert min(start for _, _, start in adapter.kline_requests) >= _ms(2026, 9, 10, 7)
    assert min(start for _, _, start in adapter.mark_requests) >= _ms(2026, 9, 10, 7)
    trade_days = _day_dirs(tmp_path / "raw", "1h", "NEWUSDT")
    mark_days = _day_dirs(tmp_path / "raw", "1h", "NEWUSDT", sub="dataset=mark_klines")
    assert trade_days == mark_days
    assert trade_days[0] == "2026-09-10"
    assert (tmp_path / "cursors" / "NEWUSDT_1h.cursor").exists()
    assert (tmp_path / "cursors" / "mark__NEWUSDT_1h.cursor").exists()


def test_frozen_manifest_sets_htf_start(tmp_path: Path) -> None:
    from src.data.backfill_cli import resolve_universe

    frozen = [f"T{i:02d}USDT" for i in range(12)]
    manifest = _write_manifest(
        tmp_path / "frozen.toml", status="FROZEN", selection_date="2024-09-28", symbols=frozen
    )
    collect = _write_collect_list(tmp_path / "collect.toml", extra=["EXTRAUSDT"])

    symbols, htf_start = resolve_universe(collect, manifest, None)

    assert htf_start == date(2024, 9, 28)
    assert set(symbols) == {*LIVE_5, "EXTRAUSDT", *frozen}
    assert symbols == sorted(symbols)

    windows = _plan(
        {"BTCUSDT": _filters("BTCUSDT")},
        intervals=("1m", "1h", "4h"),
        htf_start_date=htf_start,
    )
    starts = {w.interval: w.start_ms for w in windows}
    assert starts["1h"] == _ms(2024, 9, 28)
    assert starts["4h"] == _ms(2024, 9, 28)
    assert starts["1m"] == _ms(2025, 9, 30)  # 12 months before the run date


def test_draft_manifest_contributes_no_symbols_and_no_start(tmp_path: Path) -> None:
    from src.data.backfill_cli import resolve_universe

    manifest = _write_manifest(tmp_path / "draft.toml")
    collect = _write_collect_list(tmp_path / "collect.toml", extra=["EXTRAUSDT"])

    symbols, htf_start = resolve_universe(collect, manifest, None)

    assert htf_start is None
    assert symbols == sorted({*LIVE_5, "EXTRAUSDT"})


def test_explicit_symbols_replace_the_union_but_keep_the_frozen_start(
    tmp_path: Path,
) -> None:
    from src.data.backfill_cli import resolve_universe

    manifest = _write_manifest(
        tmp_path / "frozen.toml",
        status="FROZEN",
        selection_date="2024-09-28",
        symbols=[f"T{i:02d}USDT" for i in range(12)],
    )
    collect = _write_collect_list(tmp_path / "collect.toml")

    symbols, htf_start = resolve_universe(collect, manifest, ["ETHUSDT", "BTCUSDT"])

    assert symbols == ["BTCUSDT", "ETHUSDT"]
    assert htf_start == date(2024, 9, 28)


async def test_resume_after_kill_uses_cursor_and_store_floor(
    tmp_path: Path, session: Session
) -> None:
    import hashlib

    from src.data.backfill_cli import run_backfill

    config = _config(tmp_path, depth_months={"1h": 2})
    raw = tmp_path / "raw"

    # Run 1 is killed on its second page: the first page's days are published.
    killed = FakeAdapter([_filters("BTCUSDT")], session=session, fail_on_kline_call=2)
    with pytest.raises(RuntimeError, match="simulated kill"):
        await run_backfill(config, adapter=killed, session=session, clock=_clock(0))
    first_days = _day_dirs(raw, "1h", "BTCUSDT")
    assert 0 < len(first_days) < 62
    first_hashes = {
        p.parent.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in raw.glob("interval=1h/symbol=BTCUSDT/date=*/part.parquet")
    }
    assert (tmp_path / "cursors" / "BTCUSDT_1h.cursor").exists()

    # Run 2 resumes from the cursor: only the remaining days, no FileExistsError.
    resumed = FakeAdapter([_filters("BTCUSDT")], session=session)
    await run_backfill(config, adapter=resumed, session=session, clock=_clock(1))
    days = _day_dirs(raw, "1h", "BTCUSDT")
    assert len(days) == 62
    assert len(set(days)) == 62
    assert days[0] == "2026-07-30"
    assert days[-1] == "2026-09-29"
    assert min(start for _, _, start in resumed.kline_requests) > _ms(2026, 7, 30)
    for p in raw.glob("interval=1h/symbol=BTCUSDT/date=*/part.parquet"):
        if p.parent.name in first_hashes:
            assert hashlib.sha256(p.read_bytes()).hexdigest() == first_hashes[p.parent.name]

    # Run 3 with every cursor file deleted: the store floor stops any republish.
    for cursor in (tmp_path / "cursors").glob("*.cursor"):
        cursor.unlink()
    again = FakeAdapter([_filters("BTCUSDT")], session=session)
    report = await run_backfill(config, adapter=again, session=session, clock=_clock(2))
    assert again.kline_requests == []
    assert sum(r.total_rows for r in report.results.values()) == 0
    assert len(_day_dirs(raw, "1h", "BTCUSDT")) == 62


async def test_depth_override_moves_the_start_and_the_header(
    tmp_path: Path, session: Session
) -> None:
    from src.data.backfill_cli import run_backfill

    adapter = FakeAdapter([_filters("BTCUSDT")], session=session)
    lines: list[str] = []

    report = await run_backfill(
        _config(
            tmp_path,
            intervals=["1m"],
            depth_months={"1m": 6},
            dry_run=True,
        ),
        adapter=adapter,
        session=None,
        clock=_clock(),
        emit=lines.append,
    )

    (window,) = report.windows
    assert window.start_ms == _ms(2026, 3, 30)
    assert "1m=6 months" in lines[0]


async def test_dry_run_fetches_nothing(tmp_path: Path, session: Session) -> None:
    from src.data.backfill_cli import run_backfill

    adapter = FakeAdapter([_filters("BTCUSDT")], session=session)
    lines: list[str] = []

    report = await run_backfill(
        _config(tmp_path, datasets=["trade", "mark"], dry_run=True),
        adapter=adapter,
        session=session,
        clock=_clock(),
        emit=lines.append,
    )

    assert adapter.calls == ["exchange_info"]
    assert report.metadata_rows == 0
    assert session.execute(select(func.count()).select_from(SymbolMetadata)).scalar_one() == 0
    assert not (tmp_path / "raw").exists()
    assert not (tmp_path / "cursors").exists()
    assert any("window trade BTCUSDT 1h" in line for line in lines)
    assert any("window mark BTCUSDT 1h" in line for line in lines)


def test_main_dry_run_needs_no_database(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.data import backfill_cli

    adapter = FakeAdapter([_filters("BTCUSDT")])
    monkeypatch.setattr(backfill_cli, "BinanceUsdmAdapter", lambda: adapter)
    monkeypatch.setattr(backfill_cli, "_utc_now", _clock())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)
    manifest = _write_manifest(tmp_path / "manifest.toml")
    collect = _write_collect_list(tmp_path / "collect.toml")

    rc = backfill_cli.main(
        [
            "--symbols", "BTCUSDT",
            "--dry-run",
            "--raw-root", str(tmp_path / "raw"),
            "--manifest", str(manifest),
            "--collect-list", str(collect),
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" in out
    assert adapter.calls == ["exchange_info"]
    assert not (tmp_path / "raw").exists()


# --------------------------------------------------------------------------- #
# Task 3 - metadata for the resolved universe, symbols missing from exchangeInfo.
# --------------------------------------------------------------------------- #


async def test_cli_always_passes_universe_to_metadata(
    tmp_path: Path, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.data import backfill_cli

    captured: dict[str, Any] = {}

    def _spy(
        sess: Session,
        filters: Sequence[SymbolFilters],
        *,
        observed_at: datetime | None = None,
        universe: Any = None,
    ) -> int:
        captured["universe"] = universe
        captured["filters"] = [f.symbol for f in filters]
        return 0

    monkeypatch.setattr(backfill_cli, "refresh_symbol_metadata", _spy)
    adapter = FakeAdapter([_filters("BTCUSDT"), _filters("ETHUSDT")], session=session)

    await backfill_cli.run_backfill(
        _config(tmp_path, symbols=["BTCUSDT"], depth_months={"1h": 1}),
        adapter=adapter,
        session=session,
        clock=_clock(),
    )

    # The universe is never None (an unfiltered refresh would insert the whole
    # exchange, including 17-character contract types), and it is exactly the
    # resolved symbol set even though exchangeInfo returned more symbols.
    assert captured["universe"] is not None
    assert set(captured["universe"]) == {"BTCUSDT"}
    assert captured["filters"] == ["BTCUSDT", "ETHUSDT"]


async def test_missing_symbols_are_reported(tmp_path: Path, session: Session) -> None:
    from src.data.backfill_cli import run_backfill

    adapter = FakeAdapter([_filters("BTCUSDT")], session=session)
    lines: list[str] = []

    report = await run_backfill(
        _config(tmp_path, symbols=["BTCUSDT", "GONEUSDT"], depth_months={"1h": 1}),
        adapter=adapter,
        session=session,
        clock=_clock(),
        emit=lines.append,
        archive_client=FakeArchive({}).client(),
    )

    assert report.missing_from_exchange_info == ("GONEUSDT",)
    assert any("missing from exchangeInfo" in line and "GONEUSDT" in line for line in lines)
    # A symbol exchangeInfo does not know has no window and is never fetched.
    assert {r[0] for r in adapter.kline_requests} == {"BTCUSDT"}
    gone = [w for w in report.windows if w.symbol == "GONEUSDT"]
    assert gone and all(not w.has_window for w in gone)
    assert report.metadata_rows == 1


def test_failure_prints_type_name_never_the_database_url(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-13-31: an error whose message embeds the URL must not reach the output."""
    from src.data import backfill_cli

    url = _sqlite_url(tmp_path)
    secret_url = f"{url}?password=hunter2-secret"

    def _leaky(*args: Any, **kwargs: Any) -> int:
        raise RuntimeError(f"connection to {secret_url} failed")

    adapter = FakeAdapter([_filters("BTCUSDT")])
    monkeypatch.setattr(backfill_cli, "BinanceUsdmAdapter", lambda: adapter)
    monkeypatch.setattr(backfill_cli, "_utc_now", _clock())
    monkeypatch.setattr(backfill_cli, "refresh_symbol_metadata", _leaky)
    manifest = _write_manifest(tmp_path / "manifest.toml")
    collect = _write_collect_list(tmp_path / "collect.toml")

    rc = backfill_cli.main(
        [
            "--symbols", "BTCUSDT",
            "--intervals", "1h",
            "--datasets", "trade",
            "--database-url", secret_url,
            "--raw-root", str(tmp_path / "raw"),
            "--manifest", str(manifest),
            "--collect-list", str(collect),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "hunter2-secret" not in captured.out + captured.err
    assert "backfill: failed (RuntimeError)" in captured.err
    assert adapter.kline_requests == []


# --------------------------------------------------------------------------- #
# 13-08 Task 1 - data-sufficiency report, report file and exit codes.
# --------------------------------------------------------------------------- #

NEVER_MS = _ms(2030, 1, 1)


def _run_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    adapter: FakeAdapter,
    symbols: Sequence[str],
    *extra: str,
    minutes: int = 0,
) -> int:
    from src.data import backfill_cli

    monkeypatch.setattr(backfill_cli, "BinanceUsdmAdapter", lambda: adapter)
    monkeypatch.setattr(backfill_cli, "_utc_now", _clock(minutes))
    manifest = _write_manifest(tmp_path / "manifest.toml")
    collect = _write_collect_list(tmp_path / "collect.toml")
    return backfill_cli.main(
        [
            "--symbols", *symbols,
            "--intervals", "1h",
            "--datasets", "trade",
            "--depth-htf-months", "1",
            "--database-url", _sqlite_url(tmp_path),
            "--raw-root", str(tmp_path / "raw"),
            "--cursor-root", str(tmp_path / "cursors"),
            "--manifest", str(manifest),
            "--collect-list", str(collect),
            "--pace-seconds", "0",
            *extra,
        ]
    )


_SETTLED_FTT = _filters("FTTUSDT", status="SETTLING", delivery_ms=_ms(2026, 8, 10, 8))
_ONBOARD_NEW = _filters("NEWUSDT", onboard=datetime(2026, 9, 10, 7, tzinfo=UTC))
_PENDING_SOON = _filters(
    "SOONUSDT",
    status="PENDING_TRADING",
    onboard=datetime(2026, 10, 5, tzinfo=UTC),
    delivery_ms=FAR_FUTURE_DELIVERY_MS,
)
_UNKNOWN_DELIVERY = _filters("OLDUSDT", status="SETTLING", delivery_ms=None)


@pytest.mark.parametrize(
    ("symbol", "filters", "adapter_kwargs", "expected_rc", "expected_cause"),
    [
        ("BTCUSDT", _filters("BTCUSDT"), {}, 0, "OK"),
        (
            "NEWUSDT",
            _ONBOARD_NEW,
            {"first_ms": {"NEWUSDT": _ms(2026, 9, 10, 7)}},
            0,
            "ONBOARD_LIMITED",
        ),
        (
            "FTTUSDT",
            _SETTLED_FTT,
            {"flat_from_ms": {"FTTUSDT": _ms(2026, 8, 10, 8)}},
            0,
            "DELISTED_CAPPED",
        ),
        ("SOONUSDT", _PENDING_SOON, {}, 0, "NO_WINDOW"),
        ("BTCUSDT", _filters("BTCUSDT"), {"skip_days_ms": [_ms(2026, 9, 20)]}, 3, "GAP"),
        (
            "BTCUSDT",
            _filters("BTCUSDT"),
            {"first_ms": {"BTCUSDT": NEVER_MS}},
            3,
            "NOT_BACKFILLED",
        ),
        ("OLDUSDT", _UNKNOWN_DELIVERY, {}, 3, "UNAVAILABLE"),
    ],
)
def test_cli_exit_code_is_3_only_for_missing_data(
    tmp_path: Path,
    session_factory: sessionmaker[Session],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    symbol: str,
    filters: SymbolFilters,
    adapter_kwargs: dict[str, Any],
    expected_rc: int,
    expected_cause: str,
) -> None:
    adapter = FakeAdapter([filters], **adapter_kwargs)

    rc = _run_main(tmp_path, monkeypatch, adapter, [symbol])

    out = capsys.readouterr().out
    assert rc == expected_rc
    rows = [
        line.split()
        for line in out.splitlines()
        if line.startswith("trade ") and f" {symbol} " in line
    ]
    assert [cells[-1] for cells in rows] == [expected_cause]


def test_report_json_is_deterministic(
    tmp_path: Path,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.data.sufficiency import validate_report_file

    out_path = tmp_path / "report.json"
    first = _run_main(
        tmp_path, monkeypatch, FakeAdapter([_filters("BTCUSDT")]), ["BTCUSDT"],
        "--report-out", str(out_path),
    )
    first_bytes = out_path.read_bytes()
    # A later run on the same store: the symbol_metadata row is versioned by
    # observation time, so the second run needs its own instant.
    second = _run_main(
        tmp_path, monkeypatch, FakeAdapter([_filters("BTCUSDT")]), ["BTCUSDT"],
        "--report-out", str(out_path),
        minutes=1,
    )

    assert first == second == 0
    assert out_path.read_bytes() == first_bytes
    assert validate_report_file(out_path) == []


def test_report_states_trade_floor_is_unmeasurable(
    tmp_path: Path,
    session_factory: sessionmaker[Session],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from src.data.sufficiency import TRADE_FLOOR_NOTE

    out_path = tmp_path / "report.json"
    rc = _run_main(
        tmp_path, monkeypatch, FakeAdapter([_filters("BTCUSDT")]), ["BTCUSDT"],
        "--report-out", str(out_path),
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert TRADE_FLOOR_NOTE in out
    assert json.loads(out_path.read_text(encoding="utf-8"))["trade_floor_note"] == TRADE_FLOOR_NOTE
    assert "Phase 14" in out
    assert "projected" not in out.lower()


def test_dry_run_writes_no_report_and_exits_0(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_path = tmp_path / "report.json"
    rc = _run_main(
        tmp_path, monkeypatch, FakeAdapter([_filters("BTCUSDT")]), ["BTCUSDT"],
        "--dry-run", "--report-out", str(out_path),
    )

    assert rc == 0
    assert not out_path.exists()
    assert "DATASET" not in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# 13-08 Task 3 - archive fallback per symbol and the funding-history step.
# --------------------------------------------------------------------------- #

LISTING_HOST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
S3_NS = "http://s3.amazonaws.com/doc/2006-03-01/"
DELIVERY_MS = _ms(2026, 8, 10, 8)
_ARCHIVE_HEADER = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
    "taker_buy_volume,taker_buy_quote_volume,ignore"
)


class FakeArchive:
    """A mocked data.binance.vision: monthly kline zips and daily-1d listings.

    `available` maps a symbol to `(first_open_ms, end_open_ms_exclusive)`; every
    bar of every interval inside that range is served, and any other symbol is
    a 404. No test touches the network.
    """

    def __init__(self, available: dict[str, tuple[int, int]]) -> None:
        self.available = available
        self.requests: list[str] = []

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if url.startswith(LISTING_HOST):
            return self._listing(request.url.params.get("prefix", ""))
        return self._object(url)

    def _listing(self, prefix: str) -> httpx.Response:
        symbol = prefix.rstrip("/").split("/")[-2]
        keys: list[str] = []
        if symbol in self.available:
            first, end = self.available[symbol]
            day = first - first % DAY_MS
            while day < end:
                stamp = _dt(day).strftime("%Y-%m-%d")
                keys.append(f"{prefix}{symbol}-1d-{stamp}.zip")
                day += DAY_MS
        contents = "".join(f"<Contents><Key>{k}</Key></Contents>" for k in keys)
        body = (
            f'<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns="{S3_NS}">'
            f"<Prefix>{prefix}</Prefix><IsTruncated>false</IsTruncated>{contents}"
            "</ListBucketResult>"
        )
        return httpx.Response(200, text=body)

    def _object(self, url: str) -> httpx.Response:
        import hashlib
        import io
        import zipfile

        checksum = url.endswith(".CHECKSUM")
        parts = url.removesuffix(".CHECKSUM").split("/")
        period, symbol, interval, name = parts[-5], parts[-3], parts[-2], parts[-1]
        if period != "monthly" or symbol not in self.available:
            return httpx.Response(404)
        stamp = name.removesuffix(".zip").removeprefix(f"{symbol}-{interval}-")
        year, month = int(stamp[:4]), int(stamp[5:7])
        step = _INTERVAL_MS[interval]
        first, end = self.available[symbol]
        month_lo = _ms(year, month, 1)
        month_hi = _ms(year + (month == 12), month % 12 + 1, 1)
        opens = [
            o
            for o in range(-(-max(first, month_lo) // step) * step, min(end, month_hi), step)
        ]
        if not opens:
            return httpx.Response(404)
        rows = [_ARCHIVE_HEADER] + [
            f"{o},24.2350,24.3440,24.1750,24.2350,16620.0,{o + step - 1},"
            "403353.45570,2487,10387.1,252109.82740,0"
            for o in opens
        ]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(name.removesuffix(".zip") + ".csv", "\n".join(rows) + "\n")
        blob = buf.getvalue()
        if checksum:
            return httpx.Response(200, text=f"{hashlib.sha256(blob).hexdigest()}  {name}\n")
        return httpx.Response(200, content=blob)


def _rows_for(report: Any, dataset: str, symbol: str) -> list[Any]:
    assert report.sufficiency is not None
    return [
        r for r in report.sufficiency.rows if r.dataset == dataset and r.symbol == symbol
    ]


async def test_invalid_symbol_uses_archive_source(tmp_path: Path, session: Session) -> None:
    import polars as pl
    from src.data.backfill_cli import run_backfill

    fixture = _filters("FTTUSDT", status="SETTLING", delivery_ms=DELIVERY_MS)
    adapter = FakeAdapter([fixture], session=session, invalid_symbols=["FTTUSDT"])
    archive = FakeArchive({"FTTUSDT": (_ms(2026, 7, 1), DELIVERY_MS)})
    lines: list[str] = []

    report = await run_backfill(
        _config(tmp_path, symbols=["FTTUSDT"], depth_months={"1h": 2}),
        adapter=adapter,
        session=session,
        clock=_clock(),
        emit=lines.append,
        archive_client=archive.client(),
    )

    assert report.sources[("trade", "FTTUSDT")] == "ARCHIVE"
    days = _day_dirs(tmp_path / "raw", "1h", "FTTUSDT")
    assert days[0] == "2026-07-30"
    assert days[-1] == "2026-08-10"
    delivery_day = (
        tmp_path / "raw" / "interval=1h" / "symbol=FTTUSDT" / "date=2026-08-10" / "part.parquet"
    )
    assert pl.read_parquet(delivery_day).height == 8
    (row,) = _rows_for(report, "trade", "FTTUSDT")
    assert (row.cause, row.source, row.missing_bars) == ("DELISTED_CAPPED", "ARCHIVE", 0)
    assert report.sufficiency is not None and report.sufficiency.missing_data is False
    assert any("FTTUSDT" in line and "ARCHIVE" in line for line in lines)


async def test_archive_source_survives_a_complete_rerun(
    tmp_path: Path, session: Session
) -> None:
    from src.data.backfill_cli import run_backfill

    fixture = _filters("FTTUSDT", status="SETTLING", delivery_ms=DELIVERY_MS)
    archive = FakeArchive({"FTTUSDT": (_ms(2026, 7, 1), DELIVERY_MS)})
    config = _config(tmp_path, symbols=["FTTUSDT"], depth_months={"1h": 2})
    await run_backfill(
        config,
        adapter=FakeAdapter([fixture], session=session, invalid_symbols=["FTTUSDT"]),
        session=session,
        clock=_clock(0),
        archive_client=archive.client(),
    )

    again = FakeAdapter([fixture], session=session, invalid_symbols=["FTTUSDT"])
    report = await run_backfill(
        config,
        adapter=again,
        session=session,
        clock=_clock(1),
        archive_client=archive.client(),
    )

    # The store is complete, so REST is never asked; the source is remembered.
    assert again.kline_requests == []
    assert report.sources[("trade", "FTTUSDT")] == "ARCHIVE"
    (row,) = _rows_for(report, "trade", "FTTUSDT")
    assert (row.source, row.cause) == ("ARCHIVE", "DELISTED_CAPPED")


async def test_archive_only_symbol_capped_at_last_archive_day(
    tmp_path: Path, session: Session
) -> None:
    from src.data.backfill_cli import run_backfill

    adapter = FakeAdapter([_filters("BTCUSDT")], session=session)
    archive = FakeArchive({"GONEUSDT": (_ms(2026, 7, 1), _ms(2026, 8, 5, 12))})

    report = await run_backfill(
        _config(tmp_path, symbols=["BTCUSDT", "GONEUSDT"], depth_months={"1h": 2}),
        adapter=adapter,
        session=session,
        clock=_clock(),
        archive_client=archive.client(),
    )

    assert report.sources[("trade", "GONEUSDT")] == "ARCHIVE"
    assert {r[0] for r in adapter.kline_requests} == {"BTCUSDT"}  # REST never asked
    days = _day_dirs(tmp_path / "raw", "1h", "GONEUSDT")
    assert days[0] == "2026-07-30"
    assert days[-1] == "2026-08-05"  # capped at the last archive day
    (row,) = _rows_for(report, "trade", "GONEUSDT")
    assert row.cause == "DELISTED_CAPPED"
    assert row.expected_end_utc == "2026-08-05T12:00:00Z"  # the last archived bar
    assert row.missing_bars == 0
    gone = [w for w in report.windows if w.symbol == "GONEUSDT"]
    # The window was capped at the end of the last archive day, then trimmed to
    # the last archived bar (the day's tail after a delivery holds no bars).
    assert gone and gone[0].terminal is True and gone[0].end_ms == _ms(2026, 8, 5, 12)


def test_unavailable_symbol_exits_3(
    tmp_path: Path,
    session_factory: sessionmaker[Session],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.data import backfill_cli

    archive = FakeArchive({})
    monkeypatch.setattr(backfill_cli, "make_archive_client", archive.client)

    # GONEUSDT is in neither exchangeInfo nor the archive.
    rc = _run_main(tmp_path, monkeypatch, FakeAdapter([_filters("BTCUSDT")]), ["GONEUSDT"])

    out = capsys.readouterr().out
    assert rc == 3
    rows = [line.split() for line in out.splitlines() if line.startswith("trade ")]
    assert [cells[-1] for cells in rows] == ["UNAVAILABLE"]
    assert any("prefix=" in url and "GONEUSDT" in url for url in archive.requests)


async def test_mark_for_archive_symbol_comes_from_rest_or_is_unavailable(
    tmp_path: Path, session: Session
) -> None:
    from src.data.backfill_cli import run_backfill

    adapter = FakeAdapter([], session=session, invalid_mark_symbols=["BBBUSDT"])
    archive = FakeArchive(
        {
            "AAAUSDT": (_ms(2026, 7, 1), _ms(2026, 8, 5, 12)),
            "BBBUSDT": (_ms(2026, 7, 1), _ms(2026, 8, 5, 12)),
        }
    )

    report = await run_backfill(
        _config(
            tmp_path,
            symbols=["AAAUSDT", "BBBUSDT"],
            datasets=["trade", "mark"],
            depth_months={"1h": 2},
        ),
        adapter=adapter,
        session=session,
        clock=_clock(),
        archive_client=archive.client(),
    )

    assert report.sources[("trade", "AAAUSDT")] == "ARCHIVE"
    assert report.sources[("trade", "BBBUSDT")] == "ARCHIVE"
    assert report.sources[("mark", "AAAUSDT")] == "REST"
    assert report.sources[("mark", "BBBUSDT")] == "UNAVAILABLE"
    (mark_a,) = _rows_for(report, "mark", "AAAUSDT")
    (mark_b,) = _rows_for(report, "mark", "BBBUSDT")
    assert mark_a.cause == "DELISTED_CAPPED" and mark_a.missing_bars == 0
    assert mark_b.cause == "UNAVAILABLE"
    # Never fabricated from trade data: BBB has trade days and no mark day.
    assert _day_dirs(tmp_path / "raw", "1h", "BBBUSDT")
    assert _day_dirs(tmp_path / "raw", "1h", "BBBUSDT", sub="dataset=mark_klines") == []
    assert _day_dirs(tmp_path / "raw", "1h", "AAAUSDT", sub="dataset=mark_klines")
    assert report.sufficiency is not None and report.sufficiency.missing_data is True


async def test_funding_step_runs_per_symbol_within_bounds(
    tmp_path: Path, session: Session
) -> None:
    from src.data.backfill_cli import run_backfill

    fixtures = [
        _filters("BTCUSDT"),
        _filters("FTTUSDT", status="SETTLING", delivery_ms=DELIVERY_MS),
    ]
    adapter = FakeAdapter(fixtures, session=session, flat_from_ms={"FTTUSDT": DELIVERY_MS})

    report = await run_backfill(
        _config(tmp_path, symbols=["BTCUSDT", "FTTUSDT"], depth_months={"1h": 2}, funding=True),
        adapter=adapter,
        session=session,
        clock=_clock(),
    )

    # Start at the 1h/4h dataset start; end at min(run end, delivery cap).
    assert adapter.funding_calls == [
        ("BTCUSDT", _ms(2026, 7, 30), _ms(2026, 9, 30)),
        ("FTTUSDT", _ms(2026, 7, 30), DELIVERY_MS),
    ]
    assert report.funding is not None
    assert report.funding.rows_per_symbol == {"BTCUSDT": 0, "FTTUSDT": 0}

    skipped = FakeAdapter(fixtures, session=session)
    await run_backfill(
        _config(tmp_path / "skip", symbols=["BTCUSDT"], depth_months={"1h": 1}, funding=False),
        adapter=skipped,
        session=session,
        clock=_clock(1),
    )
    assert skipped.funding_calls == []


async def test_funding_failure_is_a_gap_row_not_a_crash(
    tmp_path: Path, session: Session
) -> None:
    from src.data.backfill_cli import run_backfill
    from src.db.models import CollectorGap

    adapter = FakeAdapter(
        [_filters("BTCUSDT"), _filters("ETHUSDT")],
        session=session,
        funding_fail_symbols=["BTCUSDT"],
    )

    report = await run_backfill(
        _config(tmp_path, symbols=["BTCUSDT", "ETHUSDT"], depth_months={"1h": 1}, funding=True),
        adapter=adapter,
        session=session,
        clock=_clock(),
    )

    assert [c[0] for c in adapter.funding_calls] == ["BTCUSDT", "ETHUSDT"]
    assert report.funding is not None and report.funding.gaps_recorded == 1
    gaps = session.execute(select(CollectorGap)).scalars().all()
    assert [(g.symbol, g.data_class) for g in gaps] == [("BTCUSDT", "funding")]
    assert report.sufficiency is not None  # the run still finished and reported


def test_no_funding_flag_skips_the_step(
    tmp_path: Path,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with_funding = FakeAdapter([_filters("BTCUSDT")])
    assert _run_main(tmp_path, monkeypatch, with_funding, ["BTCUSDT"]) == 0
    assert [c[0] for c in with_funding.funding_calls] == ["BTCUSDT"]

    without = FakeAdapter([_filters("BTCUSDT")])
    rc = _run_main(tmp_path, monkeypatch, without, ["BTCUSDT"], "--no-funding", minutes=1)
    assert rc == 0
    assert without.funding_calls == []
