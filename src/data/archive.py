"""Binance public-archive (data.binance.vision) klines as a `KlineSource` (D-08).

REST no longer serves every delisted USDT perpetual (it answers -1121 for
some), so point-in-time research needs the archive as a fallback. This module
downloads one monthly (or daily) kline zip, verifies it against its
`.CHECKSUM` sha256 file, parses the single CSV member in memory and maps each
row through the adapter's own `_row_to_kline`, so archive rows are exactly the
`Kline` values REST rows are and travel through the same paginator, quality
gate, closed-day rule and atomic Parquet publisher.

Integrity note (T-13-23): the `.CHECKSUM` file is served from the same origin
as the zip, so a match proves transport integrity only, never authenticity.
The full `check_batch` gate still runs on everything parsed here.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
import zlib
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Final

import httpx
import structlog
from src.adapters.binance_usdm import Kline, _row_to_kline

log = structlog.get_logger()

ARCHIVE_BASE_URL: Final = "https://data.binance.vision/data/futures/um"
ARCHIVE_INTERVALS: Final = ("1m", "1h", "4h", "1d")
HTTP_TIMEOUT_SECONDS: Final = 60.0
# Download and parse caps (T-13-19). A 1m month of the busiest symbol is a few
# MB compressed and about 6 MB of CSV; these leave a wide margin while still
# stopping a zip bomb long before memory pressure. Read at call time so tests
# can shrink them.
MAX_ZIP_BYTES: Final = 32 * 1024 * 1024
MAX_CSV_BYTES: Final = 128 * 1024 * 1024
_MAX_CHECKSUM_BYTES: Final = 4096

# Same shape the collect list and collector enforce (`^[A-Z0-9]+USDT$`); kept
# as a private copy so this module has no import dependency on either.
SYMBOL_RE: Final = re.compile(r"^[A-Z0-9]+USDT$")
_MONTH_RE: Final = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_DAY_RE: Final = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
_DIGEST_RE: Final = re.compile(r"^[0-9a-fA-F]{64}$")
_PERIODS: Final = ("monthly", "daily")
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_TS_MS_RE: Final = re.compile(r"^\d{13}$")
_MAX_CACHED_STAMPS: Final = 3


class ArchiveError(RuntimeError):
    """Base class for every archive ingestion failure (fail closed)."""


class ArchiveNotFound(ArchiveError):
    """The archive has no file for the requested (symbol, interval, stamp)."""


class ArchiveChecksumMismatch(ArchiveError):
    """The zip's sha256 differs from its `.CHECKSUM` file."""


class ArchiveChecksumMissing(ArchiveError):
    """A zip exists but its `.CHECKSUM` does not; never parsed unchecked."""


class ArchiveTooLarge(ArchiveError):
    """A download, listing or decompressed member exceeds its size cap."""


class ArchiveFormatError(ArchiveError):
    """Unexpected file layout: member names, timestamps, rows, checksum text."""


def make_archive_client() -> httpx.AsyncClient:
    """HTTPS client with TLS verification on and redirects off (T-13-21)."""
    return httpx.AsyncClient(
        verify=True,
        follow_redirects=False,
        timeout=HTTP_TIMEOUT_SECONDS,
    )


def archive_zip_url(symbol: str, interval: str, period: str, stamp: str) -> str:
    """Build the fixed-host zip URL after validating every component.

    Raises ValueError (caller input) before any request can be made.
    """
    if not SYMBOL_RE.match(symbol):
        raise ValueError(f"invalid archive symbol {symbol!r} (must match {SYMBOL_RE.pattern})")
    if interval not in ARCHIVE_INTERVALS:
        raise ValueError(f"unsupported archive interval {interval!r}; expected {ARCHIVE_INTERVALS}")
    if period not in _PERIODS:
        raise ValueError(f"unsupported archive period {period!r}; expected {_PERIODS}")
    pattern = _MONTH_RE if period == "monthly" else _DAY_RE
    if not pattern.match(stamp):
        raise ValueError(f"invalid {period} archive stamp {stamp!r}")
    return f"{ARCHIVE_BASE_URL}/{period}/klines/{symbol}/{interval}/{symbol}-{interval}-{stamp}.zip"


async def _get(client: httpx.AsyncClient, url: str, cap: int) -> tuple[int, bytes]:
    """GET with a hard byte cap; the body is only read for a 200 response.

    The cap is enforced on the declared Content-Length and again on the
    decoded bytes actually received, so it holds without the header.
    """
    try:
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                return response.status_code, b""
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > cap:
                raise ArchiveTooLarge(f"{url}: Content-Length {declared} exceeds {cap} bytes")
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > cap:
                    raise ArchiveTooLarge(f"{url}: body exceeds {cap} bytes")
                chunks.append(chunk)
            return 200, b"".join(chunks)
    except httpx.HTTPError as exc:
        raise ArchiveError(f"request failed for {url}: {exc!r}") from exc


def _parse_checksum(text: str, zip_name: str) -> str:
    parts = text.split()
    if len(parts) != 2 or not _DIGEST_RE.match(parts[0]):
        raise ArchiveFormatError(f"malformed checksum file for {zip_name}: {text[:120]!r}")
    if parts[1].lstrip("*") != zip_name:
        raise ArchiveFormatError(f"checksum file names {parts[1]!r}, expected {zip_name!r}")
    return parts[0].lower()


def _read_member(blob: bytes, member: str) -> str:
    """The single expected CSV member as text, read in memory under the cap."""
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            infos = zf.infolist()
            if len(infos) != 1:
                raise ArchiveFormatError(f"expected exactly one member, found {len(infos)}")
            info = infos[0]
            if info.filename != member or info.is_dir():
                raise ArchiveFormatError(f"unexpected zip member {info.filename!r}")
            if info.file_size > MAX_CSV_BYTES:
                raise ArchiveTooLarge(f"member {member} declares {info.file_size} bytes")
            with zf.open(info) as handle:
                data = handle.read(MAX_CSV_BYTES + 1)
        if len(data) > MAX_CSV_BYTES:
            raise ArchiveTooLarge(f"member {member} exceeds {MAX_CSV_BYTES} bytes")
        return data.decode("utf-8")
    except ArchiveError:
        raise
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError) as exc:
        raise ArchiveFormatError(f"unreadable zip for {member}: {exc!r}") from exc
    except UnicodeDecodeError as exc:
        raise ArchiveFormatError(f"member {member} is not UTF-8") from exc


def _parse_csv(blob: bytes, member: str, symbol: str, interval: str) -> list[Kline]:
    out: list[Kline] = []
    for index, row in enumerate(csv.reader(io.StringIO(_read_member(blob, member)))):
        if not row:
            continue
        if index == 0 and row[0] == "open_time":
            continue  # header row (open_time,open,high,...)
        if len(row) < 9:
            raise ArchiveFormatError(f"{member} row {index}: only {len(row)} columns")
        # Futures archives are epoch milliseconds; any other width means a
        # different unit (seconds, microseconds) and would land in the wrong era.
        if not (_TS_MS_RE.match(row[0]) and _TS_MS_RE.match(row[6])):
            raise ArchiveFormatError(f"{member} row {index}: non-millisecond timestamp")
        try:
            out.append(_row_to_kline(symbol, interval, row))
        except (ValueError, ArithmeticError) as exc:
            raise ArchiveFormatError(f"{member} row {index}: {exc!r}") from exc
    return out


async def fetch_archive_klines(
    client: httpx.AsyncClient,
    symbol: str,
    interval: str,
    period: str,
    stamp: str,
) -> list[Kline]:
    """Download, checksum-verify and parse one archive zip into `Kline` rows."""
    url = archive_zip_url(symbol, interval, period, stamp)
    zip_name = url.rsplit("/", 1)[1]

    status, body = await _get(client, f"{url}.CHECKSUM", _MAX_CHECKSUM_BYTES)
    if status == 404:
        zip_status, _ = await _get(client, url, MAX_ZIP_BYTES)
        if zip_status == 404:
            raise ArchiveNotFound(url)
        raise ArchiveChecksumMissing(f"{url} has no .CHECKSUM (status {status})")
    if status != 200:
        raise ArchiveError(f"unexpected status {status} for {url}.CHECKSUM")
    expected = _parse_checksum(body.decode("ascii", errors="replace"), zip_name)

    zip_status, blob = await _get(client, url, MAX_ZIP_BYTES)
    if zip_status == 404:
        raise ArchiveNotFound(url)
    if zip_status != 200:
        raise ArchiveError(f"unexpected status {zip_status} for {url}")
    if hashlib.sha256(blob).hexdigest() != expected:
        raise ArchiveChecksumMismatch(url)

    rows = _parse_csv(blob, zip_name.removesuffix(".zip") + ".csv", symbol, interval)
    log.info("archive.fetch", url=url, bytes=len(blob), rows=len(rows))
    return rows


def _ms_to_dt(ms: int) -> datetime:
    return _EPOCH + timedelta(milliseconds=ms)


def _dt_to_ms(value: datetime) -> int:
    delta = value - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1000 + delta.microseconds // 1000


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


class ArchiveKlineSource:
    """Serve archive klines through the paginator's `KlineSource` signature."""

    def __init__(self, client: httpx.AsyncClient, *, search_end_ms: int) -> None:
        self._client = client
        self._search_end_ms = search_end_ms
        # (symbol, interval, "YYYY-MM") -> rows of that month (monthly zip, or
        # every available daily zip of the month when the monthly is absent).
        self._months: OrderedDict[tuple[str, str, str], list[Kline]] = OrderedDict()

    async def _month_rows(self, symbol: str, interval: str, year: int, month: int) -> list[Kline]:
        stamp = f"{year:04d}-{month:02d}"
        key = (symbol, interval, stamp)
        cached = self._months.get(key)
        if cached is not None:
            self._months.move_to_end(key)
            return cached
        try:
            rows = await fetch_archive_klines(self._client, symbol, interval, "monthly", stamp)
        except ArchiveNotFound:
            rows = await self._daily_rows(symbol, interval, year, month)
        self._months[key] = rows
        while len(self._months) > _MAX_CACHED_STAMPS:
            self._months.popitem(last=False)
        return rows

    async def _daily_rows(self, symbol: str, interval: str, year: int, month: int) -> list[Kline]:
        rows: list[Kline] = []
        day = datetime(year, month, 1, tzinfo=UTC)
        next_y, next_m = _next_month(year, month)
        month_end = datetime(next_y, next_m, 1, tzinfo=UTC)
        while day < month_end and _dt_to_ms(day) < self._search_end_ms:
            try:
                rows += await fetch_archive_klines(
                    self._client, symbol, interval, "daily", day.strftime("%Y-%m-%d")
                )
            except ArchiveNotFound:
                pass  # a missing day is skipped forward, never interpolated
            day += timedelta(days=1)
        return rows

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        """Rows with `start_ms <= open < end_ms` from the first month that has any."""
        if start_ms is None:
            raise ValueError("ArchiveKlineSource.klines requires start_ms")
        upper = self._search_end_ms if end_ms is None else min(end_ms, self._search_end_ms)
        first = _ms_to_dt(start_ms)
        year, month = first.year, first.month
        while _dt_to_ms(datetime(year, month, 1, tzinfo=UTC)) < upper:
            rows = await self._month_rows(symbol, interval, year, month)
            window = sorted(
                (
                    k
                    for k in rows
                    if start_ms <= _dt_to_ms(k.open_time_utc) < upper
                ),
                key=lambda k: k.open_time_utc,
            )
            if window:
                return window[:limit]
            year, month = _next_month(year, month)
        return []
