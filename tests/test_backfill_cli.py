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

import pytest
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
    simulate a killed run.
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
    ) -> None:
        self._filters = list(filters)
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
