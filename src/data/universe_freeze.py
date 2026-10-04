"""Point-in-time research-universe freeze tool (Phase 13, plan 13-10; D-06..D-09, D039).

``propose`` ranks every USDT PERPETUAL contract (any exchangeInfo status) plus the
archive-only USDT symbols by trailing 30-day mean daily quote volume ending the day
before the dataset start (two years before the run date), takes the top ``top_n`` and
writes a reviewable freeze report. ``freeze`` turns an approved report into a FROZEN
manifest plus the second witness in ``scripts/decision_alignment/universe.py``.

Rules that keep survivorship bias and silent data loss out of the universe:

* Candidates include symbols delisted later. A symbol delivered before the ranking
  window, listed after its start, or without 30 full traded days is ineligible with a
  stated reason. A symbol no source can supply is listed as unrankable, never dropped.
* Daily volume comes from REST 1d klines; on ``-1121`` or an incomplete window the
  checksum-verified archive is used instead. The source is recorded per symbol.
* Ranking arithmetic is Decimal only, under a fixed local context; ties break by symbol.
* Freezing is never a side effect: it needs ``--approve <proposal_sha256>`` matching the
  recomputed report hash and an explicit ``--freeze`` flag, refuses an already frozen
  manifest or an already set witness, and writes both files atomically (the manifest is
  restored if the witness write fails). The hash routine is the gate's own
  ``compute_content_sha256`` (D-09), imported, never re-implemented.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import re
import sys
import tomllib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any, Final, Protocol

import httpx
import structlog
import tenacity
from scripts.decision_alignment.universe import (
    MANIFEST_PATH,
    REPO_ROOT,
    SYMBOL_RE,
    check_second_witness,
    compute_content_sha256,
    validate_manifest,
)
from src.adapters.binance_usdm import (
    BinanceUsdmAdapter,
    Kline,
    MarkKline,
    SymbolFilters,
    is_invalid_symbol_error,
    is_rate_limit_error,
)
from src.data.archive import (
    ArchiveError,
    ArchiveKlineSource,
    list_archive_symbols,
    make_archive_client,
)
from src.domain.canonical import sha256_hex

log = structlog.get_logger()

RANK_WINDOW_DAYS: Final = 30
TOP_N: Final = 12
REPORT_SCHEMA: Final = "research-universe-freeze-report/1"
DEFAULT_REPORT_PATH: Final = (
    REPO_ROOT / "docs" / "research" / "universe" / "research-universe-v1.freeze-report.json"
)
WITNESS_PATH: Final = REPO_ROOT / "scripts" / "decision_alignment" / "universe.py"

# Fixed pause between REST calls (about 700 candidates, weight 1 each).
REST_PACE_SECONDS = 0.1
RATE_LIMIT_ATTEMPTS: Final = 5

ELIGIBLE: Final = "ELIGIBLE"
DELIVERED_BEFORE_WINDOW: Final = "DELIVERED_BEFORE_WINDOW"
LISTED_AFTER_WINDOW_START: Final = "LISTED_AFTER_WINDOW_START"
INCOMPLETE_WINDOW: Final = "INCOMPLETE_WINDOW"
ZERO_TRADE_DAY: Final = "ZERO_TRADE_DAY"
UNAVAILABLE: Final = "UNAVAILABLE"

REST: Final = "REST"
ARCHIVE: Final = "ARCHIVE"
_NO_SOURCE: Final = "NONE"

EXIT_OK: Final = 0
EXIT_FAILED: Final = 1
EXIT_REFUSED: Final = 2
EXIT_INSUFFICIENT: Final = 3

_DAY_MS: Final = 86_400_000
_HOUR_MS: Final = 3_600_000
_EPOCH_DATE: Final = date(1970, 1, 1)
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_HASH_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_WITNESS_UNSET_RE: Final = re.compile(r"^FROZEN_CONTENT_SHA256: str \| None = None(?=\r?$)", re.M)
_WITNESS_ANY_RE: Final = re.compile(r"^FROZEN_CONTENT_SHA256: str \| None = ", re.M)
_STATE_PARAGRAPH: Final = (
    "# State: DRAFT. No symbol is listed on purpose. The volume data needed to rank symbols",
    "# does not exist yet; naming symbols now would be hand-picking, the defect D039 fixes.",
    "# Phase 13 (backfilled dataset) owns the freeze. The live-5 list is a separate config.",
)


class FreezeError(RuntimeError):
    """A refusal or a failed safety check; the freeze never proceeds past it."""


@dataclass(frozen=True)
class CandidateEvidence:
    """Ranking evidence for one candidate symbol (D-26)."""

    symbol: str
    status: str
    contract_type: str
    onboard_utc: datetime | None
    delivery_date_ms: int | None
    source: str
    days: int
    quote_volume_sum: Decimal | None
    quote_volume_mean: Decimal | None
    eligible: bool
    reason: str


@dataclass(frozen=True)
class FreezeReport:
    """The reviewable proposal; `proposal_sha256` covers every other field."""

    schema: str
    run_date: date
    dataset_start: date
    window_start: date
    window_end: date
    top_n: int
    candidates: tuple[CandidateEvidence, ...]
    ranked: tuple[tuple[str, Decimal], ...]
    proposed_symbols: tuple[str, ...]
    unrankable: tuple[tuple[str, str], ...]
    availability: tuple[tuple[str, str, str], ...]
    proposal_sha256: str


class _FreezeAdapter(Protocol):
    async def exchange_info(self) -> list[SymbolFilters]: ...

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


class _KlineSource(Protocol):
    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]: ...


# --------------------------------------------------------------------------- #
# Time helpers (integer arithmetic only)
# --------------------------------------------------------------------------- #


def dataset_start_for(run_date: date) -> date:
    """Same month and day two years earlier (29 February maps to 28 February)."""
    if run_date.month == 2 and run_date.day == 29:
        return date(run_date.year - 2, 2, 28)
    return run_date.replace(year=run_date.year - 2)


def _date_ms(day: date) -> int:
    return (day - _EPOCH_DATE).days * _DAY_MS


def _dt_ms(value: datetime) -> int:
    delta = value - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1000 + delta.microseconds // 1000


# --------------------------------------------------------------------------- #
# Candidate discovery
# --------------------------------------------------------------------------- #


def discover_candidates(
    filters: Sequence[SymbolFilters], archive_symbols: Sequence[str]
) -> list[str]:
    """PERPETUAL USDT contracts of any status, plus archive-only USDT symbols.

    A symbol that exchangeInfo lists with another contract type or quote asset
    (for example TRADIFI_PERPETUAL) is never admitted through the archive listing.
    """
    found: set[str] = set()
    other: set[str] = set()
    for f in filters:
        if f.contract_type == "PERPETUAL" and f.quote_asset == "USDT":
            if SYMBOL_RE.fullmatch(f.symbol):
                found.add(f.symbol)
        else:
            other.add(f.symbol)
    for symbol in archive_symbols:
        if SYMBOL_RE.fullmatch(symbol) and symbol not in other:
            found.add(symbol)
    return sorted(found)


# --------------------------------------------------------------------------- #
# REST / archive access
# --------------------------------------------------------------------------- #


async def _retry_sleep(seconds: Any) -> None:
    await asyncio.sleep(seconds)


async def _pace() -> None:
    if REST_PACE_SECONDS:
        await asyncio.sleep(REST_PACE_SECONDS)


async def _rest_call[T](make: Callable[[], Awaitable[T]]) -> T:
    """One paced REST call; only rate-limit errors are retried (bounded)."""

    async def _once() -> T:
        await _pace()
        return await make()

    retrying = tenacity.AsyncRetrying(
        retry=tenacity.retry_if_exception(is_rate_limit_error),
        stop=tenacity.stop_after_attempt(RATE_LIMIT_ATTEMPTS),
        wait=tenacity.wait_random_exponential(multiplier=1, max=30),
        sleep=_retry_sleep,
        reraise=True,
    )
    return await retrying(_once)


def _window_bars(rows: Sequence[Kline], start_ms: int, end_ms: int) -> list[Kline]:
    """Rows whose open time is inside [start_ms, end_ms), one per open time, sorted."""
    by_open: dict[int, Kline] = {}
    for row in rows:
        open_ms = _dt_ms(row.open_time_utc)
        if start_ms <= open_ms < end_ms:
            by_open[open_ms] = row
    return [by_open[key] for key in sorted(by_open)]


async def _rest_window(
    adapter: _FreezeAdapter, symbol: str, start_ms: int, end_ms: int
) -> list[Kline] | None:
    """REST 1d bars in the window; None when REST answers -1121 (invalid symbol)."""
    try:
        rows = await _rest_call(
            lambda: adapter.klines(
                symbol, "1d", start_ms=start_ms, end_ms=end_ms - 1, limit=RANK_WINDOW_DAYS
            )
        )
    except Exception as exc:
        if is_invalid_symbol_error(exc):
            return None
        raise
    return _window_bars(rows, start_ms, end_ms)


async def _archive_window(
    source: _KlineSource, symbol: str, start_ms: int, end_ms: int
) -> list[Kline] | None:
    """Archive 1d bars in the window (may span two months); None on an archive failure."""
    rows: list[Kline] = []
    cursor = start_ms
    try:
        while cursor < end_ms:
            page = await source.klines(
                symbol, "1d", start_ms=cursor, end_ms=end_ms, limit=RANK_WINDOW_DAYS
            )
            if not page:
                break
            rows.extend(page)
            following = max(_dt_ms(k.open_time_utc) for k in page) + 1
            if following <= cursor:
                break
            cursor = following
    except ArchiveError as exc:
        log.warning("universe_freeze.archive_failed", symbol=symbol, error=type(exc).__name__)
        return None
    return _window_bars(rows, start_ms, end_ms)


async def _gather_window(
    adapter: _FreezeAdapter, source: _KlineSource, symbol: str, start_ms: int, end_ms: int
) -> tuple[str, list[Kline]]:
    """(source, bars): REST first, the archive on -1121 or an incomplete window."""
    rest = await _rest_window(adapter, symbol, start_ms, end_ms)
    if rest is not None and len(rest) == RANK_WINDOW_DAYS:
        return REST, rest
    archive = await _archive_window(source, symbol, start_ms, end_ms)
    if archive is not None and len(archive) == RANK_WINDOW_DAYS:
        return ARCHIVE, archive
    partial: list[tuple[str, list[Kline]]] = []
    if rest:
        partial.append((REST, rest))
    if archive:
        partial.append((ARCHIVE, archive))
    if not partial:
        return _NO_SOURCE, []
    return max(partial, key=lambda item: len(item[1]))


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #


def _evidence(
    symbol: str,
    f: SymbolFilters | None,
    *,
    source: str,
    days: int,
    total: Decimal | None,
    mean: Decimal | None,
    reason: str,
) -> CandidateEvidence:
    return CandidateEvidence(
        symbol=symbol,
        status=f.status if f is not None else "ARCHIVE_ONLY",
        contract_type=f.contract_type if f is not None else "UNKNOWN",
        onboard_utc=f.onboard_time_utc if f is not None else None,
        delivery_date_ms=f.delivery_date_ms if f is not None else None,
        source=source,
        days=days,
        quote_volume_sum=total,
        quote_volume_mean=mean,
        eligible=reason == ELIGIBLE,
        reason=reason,
    )


async def _evaluate(
    adapter: _FreezeAdapter,
    source: _KlineSource,
    symbol: str,
    f: SymbolFilters | None,
    start_ms: int,
    end_ms: int,
) -> CandidateEvidence:
    """Eligibility order: delivery, onboard, fetch, count, zero-trade day."""

    def rejected(reason: str, *, src: str = _NO_SOURCE, days: int = 0) -> CandidateEvidence:
        return _evidence(symbol, f, source=src, days=days, total=None, mean=None, reason=reason)

    if f is not None and f.delivery_date_ms is not None and f.delivery_date_ms < start_ms:
        return rejected(DELIVERED_BEFORE_WINDOW)
    if f is not None and f.onboard_time_utc is not None and _dt_ms(f.onboard_time_utc) > start_ms:
        return rejected(LISTED_AFTER_WINDOW_START)
    src, bars = await _gather_window(adapter, source, symbol, start_ms, end_ms)
    if src == _NO_SOURCE:
        return rejected(UNAVAILABLE)
    if len(bars) != RANK_WINDOW_DAYS:
        return rejected(INCOMPLETE_WINDOW, src=src, days=len(bars))
    if any(bar.trade_count == 0 for bar in bars):
        return rejected(ZERO_TRADE_DAY, src=src, days=len(bars))
    with localcontext() as ctx:
        ctx.prec = 60
        total = sum((bar.quote_volume for bar in bars), Decimal(0))
        mean = total / Decimal(RANK_WINDOW_DAYS)
    return _evidence(symbol, f, source=src, days=len(bars), total=total, mean=mean, reason=ELIGIBLE)


async def _probe_trade(
    adapter: _FreezeAdapter, source: _KlineSource, symbol: str, start_ms: int
) -> str:
    try:
        rows = await _rest_call(
            lambda: adapter.klines(
                symbol, "1h", start_ms=start_ms, end_ms=start_ms + _HOUR_MS - 1, limit=1
            )
        )
    except Exception as exc:
        if not is_invalid_symbol_error(exc):
            raise
        try:
            archived = await source.klines(
                symbol, "1h", start_ms=start_ms, end_ms=start_ms + _HOUR_MS, limit=1
            )
        except ArchiveError:
            return UNAVAILABLE
        return ARCHIVE if archived else UNAVAILABLE
    return REST if rows else UNAVAILABLE


async def _probe_mark(adapter: _FreezeAdapter, symbol: str, start_ms: int) -> str:
    try:
        rows = await _rest_call(
            lambda: adapter.mark_klines(
                symbol, "1h", start_ms=start_ms, end_ms=start_ms + _HOUR_MS - 1, limit=1
            )
        )
    except Exception as exc:
        if not is_invalid_symbol_error(exc):
            raise
        return UNAVAILABLE
    return REST if rows else UNAVAILABLE


# --------------------------------------------------------------------------- #
# Report (de)serialisation and hash
# --------------------------------------------------------------------------- #


def _candidate_body(c: CandidateEvidence) -> dict[str, Any]:
    return {
        "symbol": c.symbol,
        "status": c.status,
        "contract_type": c.contract_type,
        "onboard_utc": None if c.onboard_utc is None else c.onboard_utc.isoformat(),
        "delivery_date_ms": c.delivery_date_ms,
        "source": c.source,
        "days": c.days,
        "quote_volume_sum": None if c.quote_volume_sum is None else str(c.quote_volume_sum),
        "quote_volume_mean": None if c.quote_volume_mean is None else str(c.quote_volume_mean),
        "eligible": c.eligible,
        "reason": c.reason,
    }


def _report_body(report: FreezeReport) -> dict[str, Any]:
    """Every report field except the hash, in JSON-safe form (also the hash payload)."""
    return {
        "schema": report.schema,
        "run_date": report.run_date.isoformat(),
        "dataset_start": report.dataset_start.isoformat(),
        "window_start": report.window_start.isoformat(),
        "window_end": report.window_end.isoformat(),
        "top_n": report.top_n,
        "candidates": [_candidate_body(c) for c in report.candidates],
        "ranked": [[symbol, str(total)] for symbol, total in report.ranked],
        "proposed_symbols": list(report.proposed_symbols),
        "unrankable": [[symbol, reason] for symbol, reason in report.unrankable],
        "availability": [
            {"symbol": symbol, "trade": trade, "mark": mark}
            for symbol, trade, mark in report.availability
        ],
    }


def _hash_report(report: FreezeReport) -> str:
    return sha256_hex(_report_body(report))


def _report_text(report: FreezeReport) -> str:
    doc = {**_report_body(report), "proposal_sha256": report.proposal_sha256}
    return json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def _atomic_write(path: Path, data: bytes) -> None:
    """Write via a same-directory temp file and `os.replace` (atomic on POSIX and Windows)."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_report(report: FreezeReport, path: Path) -> None:
    """Canonical JSON (sorted keys, indent 2, ASCII, trailing newline), atomic."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, _report_text(report).encode("ascii"))


def _parse_candidate(raw: dict[str, Any]) -> CandidateEvidence:
    onboard = raw["onboard_utc"]
    total = raw["quote_volume_sum"]
    mean = raw["quote_volume_mean"]
    return CandidateEvidence(
        symbol=str(raw["symbol"]),
        status=str(raw["status"]),
        contract_type=str(raw["contract_type"]),
        onboard_utc=None if onboard is None else datetime.fromisoformat(onboard),
        delivery_date_ms=None if raw["delivery_date_ms"] is None else int(raw["delivery_date_ms"]),
        source=str(raw["source"]),
        days=int(raw["days"]),
        quote_volume_sum=None if total is None else Decimal(total),
        quote_volume_mean=None if mean is None else Decimal(mean),
        eligible=bool(raw["eligible"]),
        reason=str(raw["reason"]),
    )


def _parse_report(doc: dict[str, Any]) -> FreezeReport:
    return FreezeReport(
        schema=str(doc["schema"]),
        run_date=date.fromisoformat(doc["run_date"]),
        dataset_start=date.fromisoformat(doc["dataset_start"]),
        window_start=date.fromisoformat(doc["window_start"]),
        window_end=date.fromisoformat(doc["window_end"]),
        top_n=int(doc["top_n"]),
        candidates=tuple(_parse_candidate(c) for c in doc["candidates"]),
        ranked=tuple((str(s), Decimal(v)) for s, v in doc["ranked"]),
        proposed_symbols=tuple(str(s) for s in doc["proposed_symbols"]),
        unrankable=tuple((str(s), str(r)) for s, r in doc["unrankable"]),
        availability=tuple(
            (str(a["symbol"]), str(a["trade"]), str(a["mark"])) for a in doc["availability"]
        ),
        proposal_sha256=str(doc["proposal_sha256"]),
    )


def load_report(path: Path) -> FreezeReport:
    """Read a report and recompute its hash; any edit raises FreezeError."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FreezeError(f"report unreadable: {type(exc).__name__}") from exc
    if not isinstance(doc, dict) or doc.get("schema") != REPORT_SCHEMA:
        raise FreezeError(f"report schema must be {REPORT_SCHEMA!r}")
    try:
        report = _parse_report(doc)
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise FreezeError(f"report malformed: {type(exc).__name__}") from exc
    if report.proposal_sha256 != _hash_report(report):
        raise FreezeError("proposal_sha256 does not match the report content (edited?)")
    return report


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #


async def build_freeze_report(
    adapter: _FreezeAdapter,
    archive_client: httpx.AsyncClient,
    *,
    run_date: date,
    top_n: int,
) -> FreezeReport:
    """Rank the point-in-time universe and return the (hashed) proposal."""
    dataset_start = dataset_start_for(run_date)
    window_start = dataset_start - timedelta(days=RANK_WINDOW_DAYS)
    start_ms = _date_ms(window_start)
    end_ms = _date_ms(dataset_start)

    filters = await adapter.exchange_info()
    archive_symbols = await list_archive_symbols(archive_client)
    symbols = discover_candidates(filters, archive_symbols)
    perpetual = {
        f.symbol: f for f in filters if f.contract_type == "PERPETUAL" and f.quote_asset == "USDT"
    }
    source: _KlineSource = ArchiveKlineSource(archive_client, search_end_ms=end_ms)

    evidence: list[CandidateEvidence] = []
    for symbol in symbols:
        evidence.append(
            await _evaluate(adapter, source, symbol, perpetual.get(symbol), start_ms, end_ms)
        )

    ranked_pairs = sorted(
        (
            (c.symbol, c.quote_volume_sum)
            for c in evidence
            if c.eligible and c.quote_volume_sum is not None
        ),
        key=lambda pair: (-pair[1], pair[0]),
    )
    ranked = tuple(ranked_pairs)
    proposed = tuple(sorted(symbol for symbol, _ in ranked[:top_n]))
    unrankable = tuple((c.symbol, c.reason) for c in evidence if c.reason == UNAVAILABLE)

    availability: list[tuple[str, str, str]] = []
    for symbol in proposed:
        trade = await _probe_trade(adapter, source, symbol, end_ms)
        mark = await _probe_mark(adapter, symbol, end_ms)
        availability.append((symbol, trade, mark))

    draft = FreezeReport(
        schema=REPORT_SCHEMA,
        run_date=run_date,
        dataset_start=dataset_start,
        window_start=window_start,
        window_end=dataset_start,
        top_n=top_n,
        candidates=tuple(evidence),
        ranked=ranked,
        proposed_symbols=proposed,
        unrankable=unrankable,
        availability=tuple(availability),
        proposal_sha256="",
    )
    return dataclasses.replace(draft, proposal_sha256=_hash_report(draft))


# --------------------------------------------------------------------------- #
# Freeze
# --------------------------------------------------------------------------- #


def _replace_once(text: str, pattern: str, replacement: str, label: str) -> str:
    result, count = re.subn(pattern, lambda _m: replacement, text, flags=re.M)
    if count != 1:
        raise FreezeError(f"manifest anchor {label!r} found {count} times, expected exactly 1")
    return result


def render_frozen_manifest(
    draft_text: str, *, symbols: Sequence[str], selection_date: str, content_sha256: str
) -> str:
    """Turn the DRAFT manifest text into the FROZEN text, keeping every other line."""
    if not all(SYMBOL_RE.fullmatch(s) for s in symbols):
        raise FreezeError("refusing to render an invalid symbol name")
    try:
        date.fromisoformat(selection_date)
    except ValueError as exc:
        raise FreezeError("selection_date must be an ISO date") from exc
    if not _HASH_RE.match(content_sha256):
        raise FreezeError("content_sha256 must be 64 lowercase hex characters")
    eol = "\r\n" if "\r\n" in draft_text else "\n"
    symbol_lines = "".join(f'    "{s}",{eol}' for s in sorted(symbols))
    state = eol.join(
        (
            f"# State: FROZEN on {selection_date} by python -m src.data.universe_freeze; "
            "ranking evidence in research-universe-v1.freeze-report.json.",
            "# The live-5 list is a separate config.",
        )
    )
    paragraph = r"\r?\n".join(re.escape(line) for line in _STATE_PARAGRAPH)
    text = _replace_once(draft_text, "^" + paragraph + r"(?=\r?$)", state, "state paragraph")
    text = _replace_once(text, r'^status = "DRAFT"(?=\r?$)', 'status = "FROZEN"', "status")
    text = _replace_once(
        text,
        r'^selection_date = ""(?=\r?$)',
        f'selection_date = "{selection_date}"',
        "selection_date",
    )
    text = _replace_once(
        text, r"^symbols = \[\](?=\r?$)", f"symbols = [{eol}{symbol_lines}]", "symbols"
    )
    return _replace_once(
        text,
        r'^content_sha256 = ""(?=\r?$)',
        f'content_sha256 = "{content_sha256}"',
        "content_sha256",
    )


@dataclass(frozen=True)
class _FreezePlan:
    digest: str
    manifest_text: str
    manifest_original: bytes
    witness_text: str


def _read_bytes(path: Path, what: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise FreezeError(f"{what} unreadable: {type(exc).__name__}") from exc


def _plan_freeze(
    report_path: Path, *, approve_sha256: str, manifest_path: Path, witness_path: Path
) -> _FreezePlan:
    """Every check the freeze needs, with nothing written."""
    report = load_report(report_path)
    if approve_sha256 != report.proposal_sha256:
        raise FreezeError("approval hash does not match the report proposal_sha256")

    manifest_original = _read_bytes(manifest_path, "manifest")
    draft_text = manifest_original.decode("utf-8")
    try:
        draft = tomllib.loads(draft_text)
    except tomllib.TOMLDecodeError as exc:
        raise FreezeError("manifest is not valid TOML") from exc
    if draft.get("status") != "DRAFT":
        raise FreezeError(f"manifest status is {draft.get('status')!r}, only DRAFT can be frozen")
    if draft.get("top_n") != report.top_n:
        raise FreezeError(
            f"report top_n {report.top_n} differs from manifest top_n {draft.get('top_n')!r}"
        )

    witness_text = _read_bytes(witness_path, "witness file").decode("utf-8")
    if len(_WITNESS_ANY_RE.findall(witness_text)) != 1:
        raise FreezeError("witness assignment not found exactly once")
    if not _WITNESS_UNSET_RE.search(witness_text):
        raise FreezeError("FROZEN_CONTENT_SHA256 witness is already set")

    symbols = sorted(report.proposed_symbols)
    selection_date = report.dataset_start.isoformat()
    frozen_doc = {**draft, "status": "FROZEN", "selection_date": selection_date, "symbols": symbols}
    digest = compute_content_sha256(frozen_doc)
    frozen_doc["content_sha256"] = digest
    problems = validate_manifest(frozen_doc)
    if problems:
        raise FreezeError("proposal does not validate: " + "; ".join(problems))

    manifest_text = render_frozen_manifest(
        draft_text, symbols=symbols, selection_date=selection_date, content_sha256=digest
    )
    reparsed = tomllib.loads(manifest_text)
    problems = validate_manifest(reparsed)
    if problems or compute_content_sha256(reparsed) != digest:
        raise FreezeError("rendered manifest failed validation: " + "; ".join(problems))
    problems = check_second_witness(reparsed, digest)
    if problems:
        raise FreezeError("second witness check failed: " + "; ".join(problems))

    new_witness = _WITNESS_UNSET_RE.sub(
        lambda _m: f'FROZEN_CONTENT_SHA256: str | None = "{digest}"', witness_text, count=1
    )
    return _FreezePlan(
        digest=digest,
        manifest_text=manifest_text,
        manifest_original=manifest_original,
        witness_text=new_witness,
    )


def freeze(
    report_path: Path, *, approve_sha256: str, manifest_path: Path, witness_path: Path
) -> str:
    """Write the FROZEN manifest and the witness; return the content digest."""
    plan = _plan_freeze(
        report_path,
        approve_sha256=approve_sha256,
        manifest_path=manifest_path,
        witness_path=witness_path,
    )
    _atomic_write(manifest_path, plan.manifest_text.encode("utf-8"))
    try:
        _atomic_write(witness_path, plan.witness_text.encode("utf-8"))
    except BaseException as exc:
        try:
            _atomic_write(manifest_path, plan.manifest_original)
        except BaseException as restore_exc:
            raise FreezeError(
                "witness write failed and the manifest could not be restored: "
                f"{type(restore_exc).__name__}"
            ) from exc
        raise FreezeError(f"witness write failed, manifest restored: {type(exc).__name__}") from exc
    return plan.digest


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _make_adapter() -> _FreezeAdapter:
    return BinanceUsdmAdapter()


def _make_archive_client() -> httpx.AsyncClient:
    return make_archive_client()


async def _propose(run_date: date) -> FreezeReport:
    adapter = _make_adapter()
    client = _make_archive_client()
    try:
        return await build_freeze_report(adapter, client, run_date=run_date, top_n=TOP_N)
    finally:
        await client.aclose()


def _print_review(report: FreezeReport, out: Path) -> None:
    by_symbol = {c.symbol: c for c in report.candidates}
    avail = {symbol: (trade, mark) for symbol, trade, mark in report.availability}
    eligible = sum(1 for c in report.candidates if c.eligible)
    print(
        f"universe_freeze propose: run_date={report.run_date} "
        f"dataset_start={report.dataset_start} "
        f"window=[{report.window_start}, {report.window_end}) top_n={report.top_n}"
    )
    print(f"candidates={len(report.candidates)} eligible={eligible}")
    print("proposed (rank order):")
    for rank, (symbol, total) in enumerate(report.ranked[: report.top_n], start=1):
        trade, mark = avail.get(symbol, ("?", "?"))
        print(
            f"  {rank:>2} {symbol} sum={total} source={by_symbol[symbol].source} "
            f"trade={trade} mark={mark}"
        )
    print("proposed symbols: " + " ".join(report.proposed_symbols))
    print(
        "unrankable (no source): " + (" ".join(f"{s}({r})" for s, r in report.unrankable) or "none")
    )
    flagged = [s for s, trade, mark in report.availability if UNAVAILABLE in (trade, mark)]
    print("UNAVAILABLE proposed data: " + (" ".join(flagged) or "none"))
    print(f"report: {out}")
    print(f"proposal_sha256: {report.proposal_sha256}")


def _cmd_propose(args: argparse.Namespace) -> int:
    # The default --out is the committed freeze evidence that the FROZEN manifest
    # and `reissue_collect_list` hash-check; overwriting it silently would break
    # that chain (WR-04). Refuse before any network call unless --force is given.
    if args.out.exists() and not args.force:
        raise FreezeError(
            f"--out {args.out} already exists; refusing to overwrite the freeze evidence "
            "(pass a new --out path, or --force to replace it deliberately)"
        )
    run_date: date = args.run_date or datetime.now(UTC).date()
    report = asyncio.run(_propose(run_date))
    write_report(report, args.out)
    _print_review(report, args.out)
    return EXIT_OK if len(report.proposed_symbols) >= report.top_n else EXIT_INSUFFICIENT


def _cmd_freeze(args: argparse.Namespace) -> int:
    if not args.freeze:
        plan = _plan_freeze(
            args.report,
            approve_sha256=args.approve,
            manifest_path=args.manifest,
            witness_path=args.witness,
        )
        print("universe_freeze freeze (dry run, no --freeze): nothing written")
        print(f"content_sha256: {plan.digest}")
        print("--- manifest that would be written ---")
        print(plan.manifest_text, end="")
        return EXIT_OK
    digest = freeze(
        args.report,
        approve_sha256=args.approve,
        manifest_path=args.manifest,
        witness_path=args.witness,
    )
    print(f"frozen: manifest={args.manifest} witness={args.witness} content_sha256={digest}")
    return EXIT_OK


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.data.universe_freeze",
        description=(
            "Point-in-time research-universe freeze tool (D-06..D-09). "
            "propose writes a reviewable ranking report; freeze turns an approved report "
            "into a FROZEN manifest plus the second witness."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    propose = sub.add_parser("propose", help="rank candidates and write the freeze report")
    propose.add_argument(
        "--run-date",
        type=date.fromisoformat,
        default=None,
        help="Run date, YYYY-MM-DD (default: today UTC); dataset start is two years earlier.",
    )
    propose.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help=f"Report path (default: {DEFAULT_REPORT_PATH.as_posix()}); must not exist.",
    )
    propose.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing report at --out (it is the committed freeze evidence).",
    )
    frz = sub.add_parser("freeze", help="write the FROZEN manifest and witness from a report")
    frz.add_argument("--report", type=Path, required=True, help="Report written by propose.")
    frz.add_argument("--approve", required=True, help="The report's proposal_sha256, after review.")
    frz.add_argument(
        "--freeze",
        action="store_true",
        help="Actually write the files (without it the command only prints what would change).",
    )
    frz.add_argument("--manifest", type=Path, default=MANIFEST_PATH, help="Manifest to freeze.")
    frz.add_argument("--witness", type=Path, default=WITNESS_PATH, help="Witness file to update.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Exit codes: 0 success, 1 unexpected failure, 2 refusal or usage, 3 too few eligible."""
    args = _parse_args(argv)
    try:
        if args.command == "propose":
            return _cmd_propose(args)
        return _cmd_freeze(args)
    except FreezeError as exc:
        print(f"universe_freeze: refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except Exception as exc:
        print(f"universe_freeze: failed: {type(exc).__name__}", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
