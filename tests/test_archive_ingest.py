"""Archive (data.binance.vision) ingestion as a `KlineSource` (D-08, DATA-01).

Delisted symbols that REST no longer serves are read from Binance's public
archive. Every zip is checksum-verified before parsing and its klines flow
through the same paginator, quality gate, closed-day rule and atomic
publisher as REST data. No test touches the network: every request is served
by respx, and every zip is built in-test with `zipfile`.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import io
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import httpx
import polars as pl
import pytest
import respx
from polars.testing import assert_frame_equal
from src.adapters.binance_usdm import Kline, _row_to_kline
from src.data.backfill import BackfillConfig, backfill_symbol_interval

SYMBOL = "FTTUSDT"
INTERVAL = "1h"
HOUR_MS = 3_600_000
BASE = "https://data.binance.vision/data/futures/um"
HEADER = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
    "taker_buy_volume,taker_buy_quote_volume,ignore"
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _arc() -> ModuleType:
    """The module under test, imported lazily so RED fails per test."""
    return importlib.import_module("src.data.archive")


def _ms(year: int, month: int, day: int, hour: int = 0) -> int:
    delta = datetime(year, month, day, hour, tzinfo=UTC) - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1000


def _clock(ms: int):  # type: ignore[no-untyped-def]
    fixed = _EPOCH + timedelta(milliseconds=ms)
    return lambda: fixed


def _csv_row(open_ms: int, step_ms: int = HOUR_MS, *, ts_width: int | None = None) -> str:
    """One archive CSV data row in the real 12-column layout."""
    open_txt = str(open_ms)
    close_txt = str(open_ms + step_ms - 1)
    if ts_width is not None:
        open_txt = open_txt.ljust(ts_width, "0")[:ts_width]
    return (
        f"{open_txt},24.2350,24.3440,24.1750,24.2350,16620.0,{close_txt},"
        "403353.45570,2487,10387.1,252109.82740,0"
    )


def _csv(start_ms: int, count: int, *, header: bool = True, step_ms: int = HOUR_MS) -> str:
    lines = [HEADER] if header else []
    lines += [_csv_row(start_ms + i * step_ms, step_ms) for i in range(count)]
    return "\n".join(lines) + "\n"


def _zip_bytes(csv_text: str, member: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member, csv_text)
    return buf.getvalue()


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _url(period: str, stamp: str, *, symbol: str = SYMBOL, interval: str = INTERVAL) -> str:
    return f"{BASE}/{period}/klines/{symbol}/{interval}/{symbol}-{interval}-{stamp}.zip"


def _serve(
    router: respx.MockRouter,
    period: str,
    stamp: str,
    csv_text: str,
    *,
    symbol: str = SYMBOL,
    interval: str = INTERVAL,
    digest: str | None = None,
    member: str | None = None,
) -> tuple[respx.Route, respx.Route]:
    """Mock one zip and its `.CHECKSUM`; returns (zip_route, checksum_route)."""
    name = f"{symbol}-{interval}-{stamp}"
    blob = _zip_bytes(csv_text, member if member is not None else f"{name}.csv")
    url = _url(period, stamp, symbol=symbol, interval=interval)
    checksum_route = router.get(f"{url}.CHECKSUM").respond(
        200, text=f"{digest or _sha(blob)}  {name}.zip\n"
    )
    zip_route = router.get(url).respond(200, content=blob)
    return zip_route, checksum_route


def _missing(router: respx.MockRouter, period: str, stamp: str) -> None:
    url = _url(period, stamp)
    router.get(f"{url}.CHECKSUM").respond(404)
    router.get(url).respond(404)


def _expected_klines(start_ms: int, count: int) -> list[Kline]:
    return [
        _row_to_kline(SYMBOL, INTERVAL, _csv_row(start_ms + i * HOUR_MS).split(","))
        for i in range(count)
    ]


class _RestFake:
    """REST-shaped source over pre-built klines (same rows as the archive)."""

    def __init__(self, bars: list[Kline]) -> None:
        self._bars = sorted(bars, key=lambda k: k.open_time_utc)

    async def klines(
        self,
        *,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        floor = start_ms if start_ms is not None else 0
        out = [
            k
            for k in self._bars
            if int((k.open_time_utc - _EPOCH) / timedelta(milliseconds=1)) >= floor
        ]
        return out[:limit]


def _published(root: Path, symbol: str = SYMBOL) -> dict[str, pl.DataFrame]:
    base = root / f"interval={INTERVAL}" / f"symbol={symbol}"
    if not base.exists():
        return {}
    return {f.parent.name: pl.read_parquet(f) for f in sorted(base.rglob("part.parquet"))}


OCT_2022 = _ms(2022, 10, 1)
NOV_2022 = _ms(2022, 11, 1)
OCT_ROWS = 744


# ---------------------------------------------------------------------------
# Task 1: tracer - monthly zip -> ArchiveKlineSource -> paginator -> Parquet
# ---------------------------------------------------------------------------


async def test_fetch_archive_klines_parses_month_and_skips_header() -> None:
    arc = _arc()
    with respx.mock(assert_all_called=False) as router:
        _serve(router, "monthly", "2022-10", _csv(OCT_2022, OCT_ROWS))
        async with arc.make_archive_client() as client:
            rows = await arc.fetch_archive_klines(client, SYMBOL, INTERVAL, "monthly", "2022-10")

    assert len(rows) == OCT_ROWS
    assert rows == _expected_klines(OCT_2022, OCT_ROWS)


async def test_archive_source_pages_through_a_month() -> None:
    arc = _arc()
    with respx.mock(assert_all_called=False) as router:
        zip_route, _ = _serve(router, "monthly", "2022-10", _csv(OCT_2022, OCT_ROWS))
        async with arc.make_archive_client() as client:
            source = arc.ArchiveKlineSource(client, search_end_ms=NOV_2022)
            first = await source.klines(SYMBOL, INTERVAL, start_ms=OCT_2022, limit=500)
            next_open = int((first[-1].open_time_utc - _EPOCH) / timedelta(milliseconds=1))
            second = await source.klines(
                SYMBOL, INTERVAL, start_ms=next_open + HOUR_MS, limit=500
            )
            past_end = await source.klines(SYMBOL, INTERVAL, start_ms=NOV_2022, limit=500)

        assert len(first) == 500
        assert len(second) == OCT_ROWS - 500
        assert past_end == []
        assert first + second == _expected_klines(OCT_2022, OCT_ROWS)
        # The zip is downloaded once per stamp per source instance.
        assert zip_route.call_count == 1


async def test_archive_month_publishes_same_frames_as_rest(tmp_path: Path) -> None:
    arc = _arc()
    archive_root = tmp_path / "archive"
    rest_root = tmp_path / "rest"
    cfg = BackfillConfig(interval_ms=HOUR_MS, pace_seconds=0)

    with respx.mock(assert_all_called=False) as router:
        _serve(router, "monthly", "2022-10", _csv(OCT_2022, OCT_ROWS))
        async with arc.make_archive_client() as client:
            source = arc.ArchiveKlineSource(client, search_end_ms=NOV_2022)
            archive_result = await backfill_symbol_interval(
                source,
                symbol=SYMBOL,
                interval=INTERVAL,
                start_ms=OCT_2022,
                end_ms=NOV_2022,
                raw_root=archive_root,
                config=cfg,
                clock=_clock(_ms(2026, 9, 30)),
            )

    rest_result = await backfill_symbol_interval(
        _RestFake(_expected_klines(OCT_2022, OCT_ROWS)),
        symbol=SYMBOL,
        interval=INTERVAL,
        start_ms=OCT_2022,
        end_ms=NOV_2022,
        raw_root=rest_root,
        config=cfg,
        clock=_clock(_ms(2026, 9, 30)),
    )

    archive_days = _published(archive_root)
    rest_days = _published(rest_root)
    assert len(archive_days) == 31
    assert archive_days.keys() == rest_days.keys()
    for day, frame in archive_days.items():
        assert_frame_equal(frame, rest_days[day])
    assert archive_result.rows_published == rest_result.rows_published == OCT_ROWS
    assert archive_result.structural_rejections == 0


def test_archive_module_reuses_the_adapter_row_mapping() -> None:
    """The 12-column mapping lives in the adapter only (no second mapping)."""
    source = (Path(__file__).parent.parent / "src" / "data" / "archive.py").read_text(
        encoding="utf-8"
    )
    assert "_row_to_kline" in source
    assert "Decimal(" not in source


# ---------------------------------------------------------------------------
# Task 2: fail-closed safety
# ---------------------------------------------------------------------------

SRC_ARCHIVE = Path(__file__).parent.parent / "src" / "data" / "archive.py"


async def test_checksum_mismatch_publishes_nothing(tmp_path: Path) -> None:
    arc = _arc()
    with respx.mock(assert_all_called=False) as router:
        _serve(router, "monthly", "2022-10", _csv(OCT_2022, OCT_ROWS), digest="0" * 64)
        async with arc.make_archive_client() as client:
            with pytest.raises(arc.ArchiveChecksumMismatch):
                await arc.fetch_archive_klines(client, SYMBOL, INTERVAL, "monthly", "2022-10")

            source = arc.ArchiveKlineSource(client, search_end_ms=NOV_2022)
            with pytest.raises(arc.ArchiveChecksumMismatch):
                await backfill_symbol_interval(
                    source,
                    symbol=SYMBOL,
                    interval=INTERVAL,
                    start_ms=OCT_2022,
                    end_ms=NOV_2022,
                    raw_root=tmp_path,
                    config=BackfillConfig(interval_ms=HOUR_MS, pace_seconds=0),
                    clock=_clock(_ms(2026, 9, 30)),
                )

    assert _published(tmp_path) == {}
    assert not list(tmp_path.rglob("*.parquet"))


async def test_zip_without_checksum_is_never_parsed() -> None:
    arc = _arc()
    with respx.mock(assert_all_called=False) as router:
        url = _url("monthly", "2022-10")
        router.get(f"{url}.CHECKSUM").respond(404)
        router.get(url).respond(200, content=_zip_bytes(_csv(OCT_2022, 3), "x.csv"))
        async with arc.make_archive_client() as client:
            with pytest.raises(arc.ArchiveChecksumMissing):
                await arc.fetch_archive_klines(client, SYMBOL, INTERVAL, "monthly", "2022-10")


async def test_missing_zip_and_checksum_is_not_found() -> None:
    arc = _arc()
    with respx.mock(assert_all_called=False) as router:
        _missing(router, "monthly", "2022-10")
        async with arc.make_archive_client() as client:
            with pytest.raises(arc.ArchiveNotFound):
                await arc.fetch_archive_klines(client, SYMBOL, INTERVAL, "monthly", "2022-10")


@pytest.mark.parametrize(
    "text",
    [
        f"{'a' * 64}  OTHERUSDT-1h-2022-10.zip\n",
        "not-a-digest  FTTUSDT-1h-2022-10.zip\n",
        "",
    ],
)
async def test_checksum_file_for_another_file_or_malformed_is_rejected(text: str) -> None:
    arc = _arc()
    with respx.mock(assert_all_called=False) as router:
        url = _url("monthly", "2022-10")
        router.get(f"{url}.CHECKSUM").respond(200, text=text)
        zip_route = router.get(url).respond(200, content=b"unused")
        async with arc.make_archive_client() as client:
            with pytest.raises(arc.ArchiveFormatError):
                await arc.fetch_archive_klines(client, SYMBOL, INTERVAL, "monthly", "2022-10")
        assert zip_route.call_count == 0


async def test_oversized_content_length_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    arc = _arc()
    monkeypatch.setattr(arc, "MAX_ZIP_BYTES", 200)
    with respx.mock(assert_all_called=False) as router:
        _serve(router, "monthly", "2022-10", _csv(OCT_2022, OCT_ROWS))
        async with arc.make_archive_client() as client:
            with pytest.raises(arc.ArchiveTooLarge):
                await arc.fetch_archive_klines(client, SYMBOL, INTERVAL, "monthly", "2022-10")


async def test_oversized_body_without_content_length_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arc = _arc()
    monkeypatch.setattr(arc, "MAX_ZIP_BYTES", 100)

    async def body() -> AsyncIterator[bytes]:
        for _ in range(5):
            yield b"x" * 60

    with respx.mock(assert_all_called=False) as router:
        url = _url("monthly", "2022-10")
        router.get(f"{url}.CHECKSUM").respond(200, text=f"{'a' * 64}  FTTUSDT-1h-2022-10.zip\n")
        router.get(url).mock(return_value=httpx.Response(200, content=body()))
        async with arc.make_archive_client() as client:
            with pytest.raises(arc.ArchiveTooLarge):
                await arc.fetch_archive_klines(client, SYMBOL, INTERVAL, "monthly", "2022-10")


async def test_oversized_csv_member_is_rejected_before_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arc = _arc()
    monkeypatch.setattr(arc, "MAX_CSV_BYTES", 500)
    with respx.mock(assert_all_called=False) as router:
        _serve(router, "monthly", "2022-10", _csv(OCT_2022, OCT_ROWS))  # ~100 KB CSV
        async with arc.make_archive_client() as client:
            with pytest.raises(arc.ArchiveTooLarge):
                await arc.fetch_archive_klines(client, SYMBOL, INTERVAL, "monthly", "2022-10")


def _multi_member_zip(names: list[str], csv_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in names:
            zf.writestr(name, csv_text)
    return buf.getvalue()


@pytest.mark.parametrize(
    "names",
    [
        ["FTTUSDT-1h-2022-10.csv", "extra.csv"],
        ["../evil.csv"],
        ["sub/FTTUSDT-1h-2022-10.csv"],
        ["OTHERUSDT-1h-2022-10.csv"],
        [],
    ],
)
async def test_zip_member_path_traversal_is_rejected(names: list[str]) -> None:
    arc = _arc()
    blob = _multi_member_zip(names, _csv(OCT_2022, 3))
    with respx.mock(assert_all_called=False) as router:
        url = _url("monthly", "2022-10")
        router.get(f"{url}.CHECKSUM").respond(200, text=f"{_sha(blob)}  FTTUSDT-1h-2022-10.zip\n")
        router.get(url).respond(200, content=blob)
        async with arc.make_archive_client() as client:
            with pytest.raises(arc.ArchiveFormatError):
                await arc.fetch_archive_klines(client, SYMBOL, INTERVAL, "monthly", "2022-10")


async def test_corrupt_zip_bytes_are_a_format_error() -> None:
    arc = _arc()
    blob = b"this is not a zip file"
    with respx.mock(assert_all_called=False) as router:
        url = _url("monthly", "2022-10")
        router.get(f"{url}.CHECKSUM").respond(200, text=f"{_sha(blob)}  FTTUSDT-1h-2022-10.zip\n")
        router.get(url).respond(200, content=blob)
        async with arc.make_archive_client() as client:
            with pytest.raises(arc.ArchiveFormatError):
                await arc.fetch_archive_klines(client, SYMBOL, INTERVAL, "monthly", "2022-10")


@pytest.mark.parametrize("width", [16, 10])
async def test_non_millisecond_timestamp_is_rejected(width: int) -> None:
    arc = _arc()
    bad = HEADER + "\n" + _csv_row(OCT_2022, ts_width=width) + "\n"
    with respx.mock(assert_all_called=False) as router:
        _serve(router, "monthly", "2022-10", bad)
        async with arc.make_archive_client() as client:
            with pytest.raises(arc.ArchiveFormatError):
                await arc.fetch_archive_klines(client, SYMBOL, INTERVAL, "monthly", "2022-10")


async def test_malformed_row_is_a_format_error() -> None:
    arc = _arc()
    close_ms = OCT_2022 + HOUR_MS - 1
    bad = HEADER + "\n" + f"{OCT_2022},not-a-number,1,1,1,1,{close_ms},1,1,0,0,0\n"
    with respx.mock(assert_all_called=False) as router:
        _serve(router, "monthly", "2022-10", bad)
        async with arc.make_archive_client() as client:
            with pytest.raises(arc.ArchiveFormatError):
                await arc.fetch_archive_klines(client, SYMBOL, INTERVAL, "monthly", "2022-10")


@pytest.mark.parametrize(
    ("symbol", "interval", "period", "stamp"),
    [
        ("ftt", "1h", "monthly", "2022-10"),
        ("FTT/../USDT", "1h", "monthly", "2022-10"),
        ("FTTUSDC", "1h", "monthly", "2022-10"),
        ("FTTUSDT", "2h", "monthly", "2022-10"),
        ("FTTUSDT", "1h", "monthly", "2022-13"),
        ("FTTUSDT", "1h", "monthly", "2022-10-01"),
        ("FTTUSDT", "1h", "daily", "2022-10"),
        ("FTTUSDT", "1h", "hourly", "2022-10"),
    ],
)
async def test_invalid_inputs_raise_before_any_request(
    symbol: str, interval: str, period: str, stamp: str
) -> None:
    arc = _arc()
    with respx.mock(assert_all_called=False) as router:
        router.route().respond(200)
        async with arc.make_archive_client() as client:
            with pytest.raises(ValueError, match="archive"):
                await arc.fetch_archive_klines(client, symbol, interval, period, stamp)
        with pytest.raises(ValueError, match="archive"):
            arc.archive_zip_url(symbol, interval, period, stamp)
        assert router.calls.call_count == 0


async def test_redirects_are_not_followed() -> None:
    arc = _arc()
    with respx.mock(assert_all_called=False) as router:
        url = _url("monthly", "2022-10")
        router.get(f"{url}.CHECKSUM").respond(302, headers={"Location": "https://evil.example/x"})
        evil = router.get("https://evil.example/x").respond(200, text="x")
        async with arc.make_archive_client() as client:
            with pytest.raises(arc.ArchiveError):
                await arc.fetch_archive_klines(client, SYMBOL, INTERVAL, "monthly", "2022-10")
        assert evil.call_count == 0


async def test_archive_client_pins_timeout_and_no_redirects() -> None:
    arc = _arc()
    async with arc.make_archive_client() as client:
        assert client.follow_redirects is False
        assert client.timeout.read == arc.HTTP_TIMEOUT_SECONDS


async def test_monthly_404_falls_back_to_daily_zips() -> None:
    arc = _arc()
    day1, day2 = _ms(2026, 9, 1), _ms(2026, 9, 2)
    with respx.mock(assert_all_called=False) as router:
        _missing(router, "monthly", "2026-09")
        _serve(router, "daily", "2026-09-01", _csv(day1, 24))
        _serve(router, "daily", "2026-09-02", _csv(day2, 24))
        _missing(router, "daily", "2026-09-03")
        async with arc.make_archive_client() as client:
            source = arc.ArchiveKlineSource(client, search_end_ms=_ms(2026, 9, 4))
            rows = await source.klines(SYMBOL, INTERVAL, start_ms=day1)

    assert len(rows) == 48
    assert rows[0].open_time_utc == _EPOCH + timedelta(milliseconds=day1)
    assert rows[-1].open_time_utc == _EPOCH + timedelta(milliseconds=day2 + 23 * HOUR_MS)


async def test_missing_daily_day_is_skipped_never_interpolated() -> None:
    arc = _arc()
    day1, day3 = _ms(2026, 9, 1), _ms(2026, 9, 3)
    with respx.mock(assert_all_called=False) as router:
        _missing(router, "monthly", "2026-09")
        _serve(router, "daily", "2026-09-01", _csv(day1, 24))
        _missing(router, "daily", "2026-09-02")
        _serve(router, "daily", "2026-09-03", _csv(day3, 24))
        async with arc.make_archive_client() as client:
            source = arc.ArchiveKlineSource(client, search_end_ms=_ms(2026, 9, 4))
            rows = await source.klines(SYMBOL, INTERVAL, start_ms=day1)

    opens = {int((k.open_time_utc - _EPOCH) / timedelta(milliseconds=1)) for k in rows}
    assert len(rows) == 48
    assert not any(_ms(2026, 9, 2) <= o < day3 for o in opens)


def test_archive_module_never_extracts_to_disk() -> None:
    tree = ast.parse(SRC_ARCHIVE.read_text(encoding="utf-8"))
    forbidden = {"extractall", "extract"}
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in forbidden
    ]
    assert offenders == []


# ---------------------------------------------------------------------------
# Task 3: symbol discovery (S3 listing with marker paging) and last day
# ---------------------------------------------------------------------------

LISTING_HOST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
MONTHLY_PREFIX = "data/futures/um/monthly/klines/"
S3_NS = "http://s3.amazonaws.com/doc/2006-03-01/"


def _listing_xml(
    *,
    prefixes: list[str] | None = None,
    keys: list[str] | None = None,
    truncated: bool = False,
    next_marker: str | None = None,
    prefix: str = MONTHLY_PREFIX,
) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<ListBucketResult xmlns="{S3_NS}"><Name>data.binance.vision</Name>',
        f"<Prefix>{prefix}</Prefix><MaxKeys>1000</MaxKeys><Delimiter>/</Delimiter>",
        f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>",
    ]
    if next_marker is not None:
        parts.append(f"<NextMarker>{next_marker}</NextMarker>")
    parts += [f"<CommonPrefixes><Prefix>{p}</Prefix></CommonPrefixes>" for p in prefixes or []]
    parts += [
        f"<Contents><Key>{k}</Key><Size>273</Size><StorageClass>STANDARD</StorageClass></Contents>"
        for k in keys or []
    ]
    parts.append("</ListBucketResult>")
    return "".join(parts)


def _listing_route(
    router: respx.MockRouter, pages: list[str]
) -> tuple[respx.Route, list[dict[str, str]]]:
    """Serve `pages` in order for GET on the listing host; record query params."""
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        index = min(len(seen) - 1, len(pages) - 1)
        return httpx.Response(200, text=pages[index])

    route = router.route(method="GET", url__startswith=LISTING_HOST).mock(side_effect=handler)
    return route, seen


async def test_listing_pages_and_filters_symbols() -> None:
    arc = _arc()
    page1 = _listing_xml(
        prefixes=[
            f"{MONTHLY_PREFIX}BTCUSDT/",
            f"{MONTHLY_PREFIX}BTCUSDC/",
            f"{MONTHLY_PREFIX}1000SHIBUSDT/",
        ],
        truncated=True,
        next_marker=f"{MONTHLY_PREFIX}1000SHIBUSDT/",
    )
    page2 = _listing_xml(
        prefixes=[
            f"{MONTHLY_PREFIX}BAD%2F../",
            f"{MONTHLY_PREFIX}lowerUSDT/",
            f"{MONTHLY_PREFIX}ETHUSDT/",
            f"{MONTHLY_PREFIX}BTCUSDT_250627/",
        ],
    )
    with respx.mock(assert_all_called=False) as router:
        _, seen = _listing_route(router, [page1, page2])
        async with arc.make_archive_client() as client:
            symbols = await arc.list_archive_symbols(client)

    assert symbols == ["1000SHIBUSDT", "BTCUSDT", "ETHUSDT"]
    assert len(seen) == 2
    assert seen[0]["prefix"] == MONTHLY_PREFIX
    assert seen[0]["delimiter"] == "/"
    assert "marker" not in seen[0]
    assert seen[1]["marker"] == f"{MONTHLY_PREFIX}1000SHIBUSDT/"


async def test_listing_only_supports_usdt_quote() -> None:
    arc = _arc()
    with respx.mock(assert_all_called=False) as router:
        route, _ = _listing_route(router, [_listing_xml()])
        async with arc.make_archive_client() as client:
            with pytest.raises(ValueError, match="quote"):
                await arc.list_archive_symbols(client, quote="USDC")
        assert route.call_count == 0


async def test_oversized_listing_body_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    arc = _arc()
    monkeypatch.setattr(arc, "MAX_LISTING_BYTES", 100)
    with respx.mock(assert_all_called=False) as router:
        _listing_route(router, [_listing_xml(prefixes=[f"{MONTHLY_PREFIX}BTCUSDT/"])])
        async with arc.make_archive_client() as client:
            with pytest.raises(arc.ArchiveTooLarge):
                await arc.list_archive_symbols(client)


async def test_listing_pages_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    arc = _arc()
    monkeypatch.setattr(arc, "MAX_LISTING_PAGES", 3)
    pages = [
        _listing_xml(
            prefixes=[f"{MONTHLY_PREFIX}AAA{i}USDT/"],
            truncated=True,
            next_marker=f"{MONTHLY_PREFIX}AAA{i}USDT/",
        )
        for i in range(10)
    ]
    with respx.mock(assert_all_called=False) as router:
        route, _ = _listing_route(router, pages)
        async with arc.make_archive_client() as client:
            with pytest.raises(arc.ArchiveError):
                await arc.list_archive_symbols(client)
        assert route.call_count == 3


async def test_listing_marker_must_advance() -> None:
    arc = _arc()
    stuck = _listing_xml(
        prefixes=[f"{MONTHLY_PREFIX}BTCUSDT/"],
        truncated=True,
        next_marker=f"{MONTHLY_PREFIX}BTCUSDT/",
    )
    with respx.mock(assert_all_called=False) as router:
        route, _ = _listing_route(router, [stuck])
        async with arc.make_archive_client() as client:
            with pytest.raises(arc.ArchiveError):
                await arc.list_archive_symbols(client)
        assert route.call_count == 2


async def test_listing_with_doctype_or_bad_xml_is_rejected() -> None:
    arc = _arc()
    evil = (
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>'
        f'<ListBucketResult xmlns="{S3_NS}"><IsTruncated>false</IsTruncated></ListBucketResult>'
    )
    for body in (evil, "<ListBucketResult"):
        with respx.mock(assert_all_called=False) as router:
            _listing_route(router, [body])
            async with arc.make_archive_client() as client:
                with pytest.raises(arc.ArchiveFormatError):
                    await arc.list_archive_symbols(client)


async def test_listing_http_error_is_an_archive_error() -> None:
    arc = _arc()
    with respx.mock(assert_all_called=False) as router:
        router.route(method="GET", url__startswith=LISTING_HOST).respond(403)
        async with arc.make_archive_client() as client:
            with pytest.raises(arc.ArchiveError):
                await arc.list_archive_symbols(client)


async def test_archive_last_day_from_daily_listing() -> None:
    arc = _arc()
    prefix = "data/futures/um/daily/klines/SXPUSDT/1d/"
    page1 = _listing_xml(
        keys=[
            f"{prefix}SXPUSDT-1d-2026-05-30.zip",
            f"{prefix}SXPUSDT-1d-2026-05-30.zip.CHECKSUM",
        ],
        truncated=True,
        next_marker=f"{prefix}SXPUSDT-1d-2026-05-30.zip.CHECKSUM",
        prefix=prefix,
    )
    page2 = _listing_xml(
        keys=[
            f"{prefix}SXPUSDT-1d-2026-06-01.zip",
            f"{prefix}SXPUSDT-1d-2026-06-01.zip.CHECKSUM",
            f"{prefix}SXPUSDT-1d-2026-13-40.zip",
            f"{prefix}OTHERUSDT-1d-2026-07-01.zip",
        ],
        prefix=prefix,
    )
    with respx.mock(assert_all_called=False) as router:
        _, seen = _listing_route(router, [page1, page2])
        async with arc.make_archive_client() as client:
            last = await arc.archive_last_day(client, "SXPUSDT")

    assert last == datetime(2026, 6, 1, tzinfo=UTC).date()
    assert seen[0]["prefix"] == prefix
    assert seen[1]["marker"] == f"{prefix}SXPUSDT-1d-2026-05-30.zip.CHECKSUM"


async def test_archive_last_day_is_none_without_keys() -> None:
    arc = _arc()
    with respx.mock(assert_all_called=False) as router:
        _listing_route(router, [_listing_xml(prefix="data/futures/um/daily/klines/NEWUSDT/1d/")])
        async with arc.make_archive_client() as client:
            assert await arc.archive_last_day(client, "NEWUSDT") is None


async def test_archive_last_day_validates_symbol_before_any_request() -> None:
    arc = _arc()
    with respx.mock(assert_all_called=False) as router:
        route, _ = _listing_route(router, [_listing_xml()])
        async with arc.make_archive_client() as client:
            with pytest.raises(ValueError, match="archive"):
                await arc.archive_last_day(client, "../../etc")
        assert route.call_count == 0

