"""OI snapshot collector + funding sweep with flag-never-fabricate gap journal.

DATA-02 + D-07..D-09: the canonical 5-minute open-interest loop, the
funding-rate sweep, and the opportunistic historical harvest. All three
publish to disk via the project-owned Parquet path (D-04) and advance
their watermark in PostgreSQL atomically with the snapshot insert.

The fail-closed posture lives here: any failed poll (adapter exception,
network timeout, schema mismatch) writes ONE gap row with the expected
vs observed timestamps and never advances the watermark. Downstream
consumers MUST treat gap rows as missing, NEVER as interpolated zero
(D-09).

Async / sync split:
  - The adapter calls (`adapter.open_interest`, `adapter.funding_rate`,
    `adapter.open_interest_statistics`) are `async` (the SDK is sync and
    the adapter runs each call in a worker thread).
  - The DB writes are SYNC (`session.merge`, `session.commit`) — they
    run inline inside the async function on the same event loop. SQLAlchemy
    is thread-safe at the session level, and the V1 loop is single-threaded.
  - Parquet writes are SYNC (Polars is sync).

The collector is intentionally NOT a single asyncio Task class — the
loop is owned by `main()` below (`python -m src.data.collector` runs
the 5-minute poll loop: universe, cadence, watermark session,
fail-closed handling). This module exposes three operations the loop
calls per tick:

   - `async_oi_tick(...)`                — canonical 5-min OI poll
   - `async_funding_sweep(...)`          — funding history backfill + sweep
   - `harvest_open_interest_history(...)`— opportunistic 30-day harvest
                                           (D-08, research-grade only)

`--once` runs a single tick (smoke tests); `--healthcheck` is the
container watermark-freshness probe (fails when no OI tick has
completed within 2x cadence).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import polars as pl
import structlog
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from src.adapters.binance_usdm import (
    BinanceUsdmAdapter,
    FundingTick,
    OiSnapshot,
)
from src.data.backfill import LIVE_5
from src.db.models import TICK_WIDE_SYMBOL, CollectorGap, CollectorWatermark

log = structlog.get_logger()

# Canonical 5-minute OI cadence (D-07). Overridable via
# `--cadence-seconds` (and `OI_POLL_INTERVAL_SECONDS` in .env documents
# the same baseline for operators).
COLLECTOR_CADENCE_SECONDS = 300.0

# First funding sweep looks back 8h (one funding interval) so a fresh
# deploy fetches a bounded window; later sweeps resume from watermarks.
FUNDING_BOOTSTRAP_LOOKBACK_MS = 8 * 60 * 60_000

# Structural adapter surface used by the collector (IN-01). Production
# passes a `BinanceUsdmAdapter`; tests inject a `FakeAdapter`. A
# `Protocol` (not a `BinanceUsdmAdapter | object` union) means mypy
# checks the adapter boundary instead of collapsing to `object`.
class AdapterLike(Protocol):
    """Anything that quacks like the project adapter for OI/funding."""

    async def open_interest(self, symbol: str) -> OiSnapshot: ...
    async def funding_rate(
        self,
        symbol: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1000,
    ) -> list[FundingTick]: ...
    async def open_interest_statistics(
        self, symbol: str, period: str, limit: int = 30
    ) -> list[OiSnapshot]: ...


# --------------------------------------------------------------------------- #
# Result types — single source of truth for the three operations.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class OITickResult:
    """Outcome of one `async_oi_tick` call."""

    snapshots_inserted: int
    watermarks_advanced: int
    gaps_recorded: int


@dataclass(frozen=True)
class FundingSweepResult:
    """Outcome of one `async_funding_sweep` call.

    `empty` distinguishes "genuinely nothing new" (True, no gaps) from a
    blind sweep — callers must not mistake an upstream outage that
    yielded zero rows for "caught up".
    """

    funding_inserted: int
    watermarks_advanced: int
    gaps_recorded: int
    empty: bool = False


# --------------------------------------------------------------------------- #
# Parquet writers — one per data class. Append-free by design: each tick
# writes its own file so D-04 (immutability) holds trivially.
# --------------------------------------------------------------------------- #


_OI_SCHEMA: dict[str, pl.DataType] = {
    "symbol": pl.String(),
    "observed_at_utc": pl.Datetime(time_unit="ms", time_zone="UTC"),
    "open_interest": pl.Decimal(scale=8),
    "source": pl.String(),
}

_FUNDING_SCHEMA: dict[str, pl.DataType] = {
    "symbol": pl.String(),
    "funding_time_utc": pl.Datetime(time_unit="ms", time_zone="UTC"),
    "funding_rate": pl.Decimal(scale=10),
    "mark_price": pl.Decimal(scale=8),
}


def _tick_iso(dt: datetime) -> str:
    """ISO-8601 filename-safe tick timestamp."""
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _guard_no_overwrite(path: Path) -> None:
    """Enforce D-04 immutability for tick files (same rule as `publish_batch`).

    Two ticks in the same second (or a retried tick) resolve to the same
    filename — overwriting would silently destroy evidence, so refuse.
    """
    if path.exists():
        raise FileExistsError(
            f"refusing to overwrite immutable tick file at {path} "
            "(D-04 immutability rule)."
        )


def _write_oi_snapshot(snap: OiSnapshot, raw_root: Path) -> Path:
    """Write one OI snapshot to a per-tick Parquet file.

    Layout: `<root>/data_class=oi/symbol=<sym>/date=<YYYY-MM-DD>/tick-<iso>.parquet`
    """
    day = snap.observed_at_utc.date().isoformat()
    path = (
        raw_root
        / "data_class=oi"
        / f"symbol={snap.symbol}"
        / f"date={day}"
        / f"tick-{_tick_iso(snap.observed_at_utc)}.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    _guard_no_overwrite(path)
    df = pl.DataFrame(
        [
            {
                "symbol": snap.symbol,
                "observed_at_utc": snap.observed_at_utc,
                "open_interest": snap.open_interest,
                "source": snap.source,
            }
        ],
        schema=_OI_SCHEMA,
    )
    df.write_parquet(path)
    return path


def _write_oi_research_snapshot(snap: OiSnapshot, raw_root: Path) -> Path:
    """Write one research-grade OI snapshot to the research partition.

    Layout: `<root>/data_class=oi_research/symbol=<sym>/date=<YYYY-MM-DD>/tick-<iso>.parquet`
    """
    day = snap.observed_at_utc.date().isoformat()
    path = (
        raw_root
        / "data_class=oi_research"
        / f"symbol={snap.symbol}"
        / f"date={day}"
        / f"tick-{_tick_iso(snap.observed_at_utc)}.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    _guard_no_overwrite(path)
    df = pl.DataFrame(
        [
            {
                "symbol": snap.symbol,
                "observed_at_utc": snap.observed_at_utc,
                "open_interest": snap.open_interest,
                "source": snap.source,
            }
        ],
        schema=_OI_SCHEMA,
    )
    df.write_parquet(path)
    return path


def _write_funding_tick(tick: FundingTick, raw_root: Path) -> Path:
    """Write one funding tick to a per-sweep Parquet file.

    Layout: `<root>/data_class=funding/symbol=<sym>/date=<YYYY-MM-DD>/sweep-<iso>.parquet`
    """
    day = tick.funding_time_utc.date().isoformat()
    path = (
        raw_root
        / "data_class=funding"
        / f"symbol={tick.symbol}"
        / f"date={day}"
        / f"sweep-{_tick_iso(tick.funding_time_utc)}.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    _guard_no_overwrite(path)
    df = pl.DataFrame(
        [
            {
                "symbol": tick.symbol,
                "funding_time_utc": tick.funding_time_utc,
                "funding_rate": tick.funding_rate,
                "mark_price": tick.mark_price if tick.mark_price is not None else None,
            }
        ],
        schema=_FUNDING_SCHEMA,
    )
    df.write_parquet(path)
    return path


# --------------------------------------------------------------------------- #
# Gap-journal helper.
# --------------------------------------------------------------------------- #


def _record_gap(
    session: Session,
    *,
    symbol: str,
    data_class: str,
    expected_utc: datetime,
    observed_utc: datetime,
    reason: str,
) -> None:
    """Insert an idempotent gap row (D-09).

    PK = `(symbol, data_class, expected_utc)`. A second call with the
    same expected timestamp + data_class is a no-op (D-09 idempotent).
    `TICK_WIDE_SYMBOL` represents a tick-wide failure (the whole poll
    missed rather than one specific symbol) — never NULL, because
    PostgreSQL rejects NULL in PK columns.
    """
    # Truncate to the String(256) column BEFORE insert: an unbounded
    # `adapter_error: ...` message would otherwise make the very insert
    # meant to record the outage fail on PostgreSQL with a length
    # violation (SQLite ignores the length and masked this).
    # Use merge() so the insert is idempotent on the PK.
    session.merge(
        CollectorGap(
            symbol=symbol,
            data_class=data_class,
            expected_utc=expected_utc,
            observed_utc=observed_utc,
            reason=reason[:256],
            recorded_at_utc=datetime.now(UTC),
        )
    )
    session.commit()


# --------------------------------------------------------------------------- #
# Watermark helper.
# --------------------------------------------------------------------------- #


def _advance_watermark(
    session: Session,
    *,
    symbol: str,
    data_class: str,
    last_tick_utc: datetime,
    updated_at_utc: datetime,
) -> None:
    """Upsert the watermark row for one (symbol, data_class)."""
    session.merge(
        CollectorWatermark(
            symbol=symbol,
            data_class=data_class,
            last_tick_utc=last_tick_utc,
            updated_at_utc=updated_at_utc,
        )
    )


# --------------------------------------------------------------------------- #
# Public API.
# --------------------------------------------------------------------------- #


async def async_oi_tick(
    adapter: AdapterLike,
    session: Session,
    *,
    universe: Sequence[str],
    expected_utc: datetime,
    observed_utc: datetime,
    raw_root: Path,
    skip: bool = False,
) -> OITickResult:
    """Run one canonical 5-minute OI tick (D-07).

    Three outcomes:
      - Healthy: one snapshot per universe symbol + watermark advance,
        all in ONE transaction. `gaps_recorded == 0`.
      - Per-symbol adapter error: the failed symbol gets its own gap row
        while healthy symbols still commit + advance — one bad symbol
        never blinds the whole tick. `gaps_recorded` counts failed symbols.
      - Skipped (`skip=True`): caller signals the scheduled tick did not
        run (e.g. process restart). ONE tick-wide gap row with expected
        vs observed timestamps, no adapter call.

    Atomicity: snapshot file writes happen BEFORE `session.commit()`. A
    disk/permission failure in the write+commit section records a
    tick-wide gap row and re-raises — a half-written tick is never left
    without a journal entry.
    """
    if skip:
        _record_gap(
            session,
            symbol=TICK_WIDE_SYMBOL,
            data_class="oi",
            expected_utc=expected_utc,
            observed_utc=observed_utc,
            reason="scheduled_tick_skipped",
        )
        return OITickResult(
            snapshots_inserted=0, watermarks_advanced=0, gaps_recorded=1
        )

    # Poll the adapter sequentially (5 symbols — bounded concurrency
    # unnecessary), isolating failures per symbol.
    snapshots: list[OiSnapshot] = []
    gaps = 0
    for sym in universe:
        try:
            snap = await adapter.open_interest(sym)
        except Exception as exc:
            _record_gap(
                session,
                symbol=sym,
                data_class="oi",
                expected_utc=expected_utc,
                observed_utc=observed_utc,
                reason=f"adapter_error: {type(exc).__name__}: {exc}",
            )
            gaps += 1
            continue
        snapshots.append(snap)

    # Write snapshot files + advance watermarks in ONE transaction. Any
    # failure journals a gap row before propagating (never half-fail
    # without a gap).
    inserted = 0
    try:
        for snap in snapshots:
            _write_oi_snapshot(snap, raw_root)
            _advance_watermark(
                session,
                symbol=snap.symbol,
                data_class="oi",
                last_tick_utc=snap.observed_at_utc,
                updated_at_utc=observed_utc,
            )
            inserted += 1
        session.commit()
    except Exception as exc:
        session.rollback()
        _record_gap(
            session,
            symbol=TICK_WIDE_SYMBOL,
            data_class="oi",
            expected_utc=expected_utc,
            observed_utc=observed_utc,
            reason=f"write_error: {type(exc).__name__}: {exc}",
        )
        raise

    return OITickResult(
        snapshots_inserted=inserted,
        watermarks_advanced=inserted,
        gaps_recorded=gaps,
    )


async def async_funding_sweep(
    adapter: AdapterLike,
    session: Session,
    *,
    universe: Sequence[str],
    observed_utc: datetime,
    raw_root: Path,
    since_ms: int,
    end_ms: int | None = None,
    limit: int = 1000,
) -> FundingSweepResult:
    """Run one funding-rate sweep across the universe (D-08).

    Backfill is `since_ms`-driven: the caller passes the start of the
    window to fetch (typically `last_watermark + 1` or `0` for the first
    bootstrap). Each symbol's tick writes to the `data_class=funding`
    partition AND advances the `data_class=funding` watermark — separate
    namespace from the OI loop (D-08).

    On adapter exception: a per-symbol gap row and no watermark advance
    for the failed symbol; healthy symbols still commit.
    """
    ticks: list[FundingTick] = []
    gaps = 0
    for sym in universe:
        try:
            sym_ticks = await adapter.funding_rate(
                symbol=sym, start_ms=since_ms, end_ms=end_ms, limit=limit
            )
        except Exception as exc:
            _record_gap(
                session,
                symbol=sym,
                data_class="funding",
                expected_utc=datetime.fromtimestamp(since_ms / 1000, tz=UTC),
                observed_utc=observed_utc,
                reason=f"adapter_error: {type(exc).__name__}: {exc}",
            )
            gaps += 1
            continue
        ticks.extend(sym_ticks)

    # Write every tick + advance watermarks per symbol, atomically. A
    # write/commit failure journals a gap row before propagating.
    inserted = 0
    latest_per_symbol: dict[str, datetime] = {}
    try:
        for tick in ticks:
            _write_funding_tick(tick, raw_root)
            cur = latest_per_symbol.get(tick.symbol)
            if cur is None or tick.funding_time_utc > cur:
                latest_per_symbol[tick.symbol] = tick.funding_time_utc
            inserted += 1
        for sym, last_tick in latest_per_symbol.items():
            _advance_watermark(
                session,
                symbol=sym,
                data_class="funding",
                last_tick_utc=last_tick,
                updated_at_utc=observed_utc,
            )
        session.commit()
    except Exception as exc:
        session.rollback()
        _record_gap(
            session,
            symbol=TICK_WIDE_SYMBOL,
            data_class="funding",
            expected_utc=datetime.fromtimestamp(since_ms / 1000, tz=UTC),
            observed_utc=observed_utc,
            reason=f"write_error: {type(exc).__name__}: {exc}",
        )
        raise

    return FundingSweepResult(
        funding_inserted=inserted,
        watermarks_advanced=len(latest_per_symbol),
        gaps_recorded=gaps,
        empty=(inserted == 0 and gaps == 0),
    )


async def harvest_open_interest_history(
    adapter: AdapterLike,
    session: Session,
    *,
    universe: Sequence[str],
    observed_utc: datetime,
    raw_root: Path,
    lookback_days: int,
    period: str = "1d",
) -> int:
    """One-shot opportunistic openInterestHist harvest (D-08).

    The `/futures/data/openInterestHist` endpoint only exposes the
    latest ~30 days. We harvest at bootstrap as a one-shot, research-
    grade data source — NEVER the forward source. Each harvested row
    is tagged `source="research"` and lives under `data_class=oi_research`
    so downstream consumers (Phase 6/7) can distinguish it from the
    canonical 5-minute snapshots.

    Returns the total number of harvested rows. Watermarks are NOT
    advanced — this is not the forward source. An adapter exception for
    one symbol journals a per-symbol gap row (no watermark advance, which
    the harvest never does) while the remaining symbols still harvest.
    """
    rows_inserted = 0
    for sym in universe:
        try:
            snapshots = await adapter.open_interest_statistics(
                symbol=sym, period=period, limit=lookback_days
            )
        except Exception as exc:
            _record_gap(
                session,
                symbol=sym,
                data_class="oi_research_harvest",
                expected_utc=observed_utc,
                observed_utc=observed_utc,
                reason=f"adapter_error: {type(exc).__name__}: {exc}",
            )
            continue
        for snap in snapshots:
            _write_oi_research_snapshot(snap, raw_root)
            rows_inserted += 1
    # Mark the harvest completion in the gap journal — informational,
    # not a real gap. Keeps the audit trail unified.
    _record_gap(
        session,
        symbol=TICK_WIDE_SYMBOL,
        data_class="oi_research_harvest",
        expected_utc=datetime.fromtimestamp(0, tz=UTC),  # sentinel
        observed_utc=observed_utc,
        reason=f"harvest_complete: rows={rows_inserted} lookback_days={lookback_days}",
    )
    return rows_inserted


# --------------------------------------------------------------------------- #
# Runner entrypoint — the 5-minute poll loop (D-07).
# --------------------------------------------------------------------------- #


def _resolve_database_url(explicit: str | None) -> str:
    """Resolve the sync DB URL: explicit flag, then env (SYNC first).

    Raises loudly when nothing is set — the loop must never start
    without a watermark session (fail closed, no phantom ticks).
    """
    url = (
        explicit
        or os.environ.get("DATABASE_URL_SYNC")
        or os.environ.get("DATABASE_URL")
    )
    if not url:
        raise RuntimeError(
            "refusing collector start: neither --database-url nor "
            "DATABASE_URL_SYNC nor DATABASE_URL is set — no watermark "
            "session, no ticks"
        )
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _make_sync_engine(database_url: str | None) -> Engine:
    """Build the sync engine for the collector loop / healthcheck."""
    return create_engine(_resolve_database_url(database_url), future=True)


def _floor_to_cadence(dt: datetime, cadence_seconds: float) -> datetime:
    """Floor `dt` to the cadence grid — the tick's expected timestamp."""
    epoch_s = int(dt.timestamp())
    step = max(1, int(cadence_seconds))
    return datetime.fromtimestamp(epoch_s - (epoch_s % step), tz=UTC)


def _funding_since_ms(
    session: Session, universe: Sequence[str], now_ms: int
) -> int:
    """Resume each symbol just after its funding watermark.

    Symbols without a watermark (fresh deploy) start one funding
    interval back so the first sweep is bounded; resuming at
    `watermark + 1` never re-fetches an already-written tick (the
    tick-file immutability guard would refuse the overwrite).
    """
    starts: list[int] = []
    for sym in universe:
        row = session.execute(
            select(CollectorWatermark).where(
                CollectorWatermark.symbol == sym,
                CollectorWatermark.data_class == "funding",
            )
        ).scalar_one_or_none()
        if row is None or row.last_tick_utc is None:
            starts.append(now_ms - FUNDING_BOOTSTRAP_LOOKBACK_MS)
        else:
            starts.append(int(row.last_tick_utc.timestamp() * 1000) + 1)
    return min(starts)


async def _run_once_tick(
    adapter: AdapterLike,
    session: Session,
    *,
    universe: Sequence[str],
    raw_root: Path,
    observed_utc: datetime,
    cadence_seconds: float = COLLECTOR_CADENCE_SECONDS,
) -> tuple[OITickResult, FundingSweepResult]:
    """Run one OI tick + one funding sweep (the unit the loop repeats)."""
    expected_utc = _floor_to_cadence(observed_utc, cadence_seconds)
    oi = await async_oi_tick(
        adapter,
        session,
        universe=universe,
        expected_utc=expected_utc,
        observed_utc=observed_utc,
        raw_root=raw_root,
    )
    now_ms = int(observed_utc.timestamp() * 1000)
    since_ms = _funding_since_ms(session, universe, now_ms)
    funding = await async_funding_sweep(
        adapter,
        session,
        universe=universe,
        observed_utc=observed_utc,
        raw_root=raw_root,
        since_ms=since_ms,
        end_ms=now_ms,
    )
    return oi, funding


def _check_health(
    database_url: str | None,
    *,
    universe: Sequence[str],
    max_age_seconds: float,
) -> int:
    """Watermark-freshness probe for the container HEALTHCHECK.

    Exit 0 iff every universe symbol has an OI watermark updated within
    `max_age_seconds` (2x cadence); otherwise exit 1 with the stale
    symbols on stderr. A wedged loop surfaces as unhealthy instead of
    reporting healthy forever.
    """
    session: Session | None = None
    try:
        engine = _make_sync_engine(database_url)
        session = sessionmaker(bind=engine)()
        now = datetime.now(UTC)
        stale: list[str] = []
        for sym in universe:
            row = session.execute(
                select(CollectorWatermark).where(
                    CollectorWatermark.symbol == sym,
                    CollectorWatermark.data_class == "oi",
                )
            ).scalar_one_or_none()
            if row is None or row.updated_at_utc is None:
                stale.append(f"{sym}:no-watermark")
                continue
            updated = row.updated_at_utc
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
            age = (now - updated).total_seconds()
            if age > max_age_seconds:
                stale.append(f"{sym}:age={age:.0f}s")
        if stale:
            print(
                f"collector-health: UNHEALTHY — {'; '.join(stale)}",
                file=sys.stderr,
            )
            return 1
        print(f"collector-health: OK — {len(universe)} symbols fresh")
        return 0
    except Exception as exc:
        print(
            f"collector-health: UNKNOWN — {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    finally:
        if session is not None:
            session.close()


def _parse_collector_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.data.collector",
        description=(
            "Canonical 5-minute OI poll loop + funding sweep (D-07/D-08). "
            "Snapshots land in the Parquet raw store; watermarks advance "
            "in PostgreSQL; failures journal gap rows and never advance."
        ),
    )
    parser.add_argument(
        "--universe",
        nargs="+",
        default=list(LIVE_5),
        help="Symbols to poll (default: live-5).",
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path("data") / "raw",
        help="Parquet raw-store root (default: data/raw).",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Sync DB URL (default: DATABASE_URL_SYNC / DATABASE_URL env).",
    )
    parser.add_argument(
        "--cadence-seconds",
        type=float,
        default=COLLECTOR_CADENCE_SECONDS,
        help="Poll cadence in seconds (default: 300).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single tick + sweep, then exit (smoke tests).",
    )
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Watermark-freshness probe: exit 0 iff every universe symbol "
        "has an OI watermark newer than 2x cadence.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the collector: loop (default), one tick (`--once`), or probe."""
    args = _parse_collector_args(argv)
    universe: list[str] = list(args.universe) or list(LIVE_5)
    raw_root = Path(args.raw_root)
    cadence: float = float(args.cadence_seconds)
    if args.healthcheck:
        return _check_health(
            args.database_url,
            universe=universe,
            max_age_seconds=2 * cadence,
        )
    try:
        engine = _make_sync_engine(args.database_url)
    except RuntimeError as exc:
        print(f"collector: {exc}", file=sys.stderr)
        return 2
    adapter = BinanceUsdmAdapter()
    session_factory = sessionmaker(bind=engine)
    if args.once:
        session = session_factory()
        try:
            observed = datetime.now(UTC)
            oi, funding = asyncio.run(
                _run_once_tick(
                    adapter,
                    session,
                    universe=universe,
                    raw_root=raw_root,
                    observed_utc=observed,
                    cadence_seconds=cadence,
                )
            )
        finally:
            session.close()
        print(
            f"collector-once: oi={oi.snapshots_inserted} "
            f"funding={funding.funding_inserted} "
            f"gaps={oi.gaps_recorded + funding.gaps_recorded}"
        )
        return 0
    print(
        f"collector: loop start universe={len(universe)} "
        f"cadence={cadence}s raw_root={raw_root}"
    )
    try:
        while True:
            observed = datetime.now(UTC)
            session = session_factory()
            try:
                oi, funding = asyncio.run(
                    _run_once_tick(
                        adapter,
                        session,
                        universe=universe,
                        raw_root=raw_root,
                        observed_utc=observed,
                        cadence_seconds=cadence,
                    )
                )
                log.info(
                    "collector.tick",
                    oi=oi.snapshots_inserted,
                    funding=funding.funding_inserted,
                    gaps=oi.gaps_recorded + funding.gaps_recorded,
                )
            except Exception:
                # Fail-closed accounting already journaled a gap row
                # inside the tick; the loop itself must survive the
                # unexpected (never crash-loop silently — the exception
                # is logged with traceback).
                log.exception("collector.tick.failed")
            finally:
                session.close()
            time.sleep(cadence)
    except KeyboardInterrupt:
        print("collector: stopping")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
