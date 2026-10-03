"""Tests for the OI/funding collector + gap journal (02-04 Task 2).

The 02-04 plan calls out five behaviors (02-04-PLAN §tasks[2].behavior):

  1. Healthy tick writes one snapshot per live-5 symbol and advances
     five watermarks atomically.
  2. Adapter exception writes a gap row and no snapshot and no watermark
     advance.
  3. Skipped scheduled tick records expected vs observed timestamps
     with no interpolated value.
  4. Funding sweep writes to its own partition and watermark namespace,
     separate from OI.
  5. Opportunistic openInterestHist harvest rows carry a research-grade
     source tag distinct from canonical collector rows.

TDD discipline: RED → GREEN. These tests are the RED phase — they MUST
fail until `src/data/collector.py` is implemented.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from src.adapters.binance_usdm import FundingTick, OiSnapshot
from src.data.backfill import LIVE_5
from src.data.collector import (
    FundingSweepResult,
    OITickResult,
    async_funding_sweep,
    async_oi_tick,
    harvest_open_interest_history,
)
from src.db.models import Base, CollectorGap, CollectorWatermark

# --------------------------------------------------------------------------- #
# Test scaffold.
# --------------------------------------------------------------------------- #


def _mk_oi_snapshot(symbol: str, *, value: str = "12345.678") -> OiSnapshot:
    """Build a canonical OI snapshot for tests."""
    return OiSnapshot(
        symbol=symbol,
        observed_at_utc=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
        open_interest=Decimal(value),
    )


def _mk_funding_tick(symbol: str, *, rate: str = "0.0001") -> FundingTick:
    """Build a canonical funding tick for tests."""
    return FundingTick(
        symbol=symbol,
        funding_time_utc=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
        funding_rate=Decimal(rate),
        mark_price=Decimal("50000.00"),
    )


class FakeAdapter:
    """Fake Binance adapter for collector tests.

    Configures per-method responses. Each method is `async` because the
    real adapter is async; tests inject this in place of the real SDK
    client.
    """

    def __init__(
        self,
        *,
        oi_responses: list[OiSnapshot | Exception] | None = None,
        funding_responses: list[list[FundingTick] | Exception] | None = None,
        oi_hist_response: dict[str, list[OiSnapshot]] | None = None,
        server_time_response: datetime | Exception | None = None,
    ) -> None:
        self._server_time = server_time_response
        self.server_time_calls = 0
        self._oi = list(oi_responses or [])
        self._funding = list(funding_responses or [])
        self._oi_hist = oi_hist_response or {}
        self.oi_calls: list[str] = []
        self.funding_calls: list[tuple[str | None, int | None, int | None]] = []
        self.oi_hist_calls: list[tuple[str, str, int]] = []

    async def open_interest(self, symbol: str) -> OiSnapshot:
        self.oi_calls.append(symbol)
        if not self._oi:
            raise RuntimeError(f"FakeAdapter.open_interest: no response queued for {symbol}")
        nxt = self._oi.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    async def funding_rate(
        self,
        symbol: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1000,
    ) -> list[FundingTick]:
        self.funding_calls.append((symbol, start_ms, end_ms))
        if not self._funding:
            return []
        nxt = self._funding.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    async def open_interest_statistics(
        self,
        symbol: str,
        period: str,
        limit: int = 30,
    ) -> list[OiSnapshot]:
        self.oi_hist_calls.append((symbol, period, limit))
        return list(self._oi_hist.get(symbol, []))

    async def server_time(self) -> datetime:
        self.server_time_calls += 1
        if isinstance(self._server_time, Exception):
            raise self._server_time
        if self._server_time is None:
            return datetime.now(UTC)
        return self._server_time


@pytest.fixture
def session() -> Iterator[Session]:
    """In-memory SQLite session with the four-table schema applied."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalize a datetime to naive UTC for SQLite roundtrip comparisons.

    SQLite drops tzinfo on roundtrip (it has no TIMESTAMPTZ type), so
    values read back from the DB are naive even when we wrote tz-aware
    datetimes. Production uses PostgreSQL TIMESTAMPTZ which preserves
    tzinfo exactly. For tests, comparing via `epoch_ms` is the cleanest
    cross-DB equivalence.
    """
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _epoch_ms(dt: datetime) -> int:
    """Compare datetimes across the SQLite roundtrip via epoch ms.

    SQLite drops tzinfo on roundtrip; naive datetimes read back are
    assumed to be UTC (the convention we wrote them in). Production uses
    PostgreSQL TIMESTAMPTZ which preserves tzinfo exactly.
    """
    if dt.tzinfo is None:
        # Already-naive: assume UTC (SQLite convention for our writes).
        return int(dt.replace(tzinfo=UTC).timestamp() * 1000)
    return int(dt.timestamp() * 1000)


# --------------------------------------------------------------------------- #
# Test 1 — healthy tick writes one snapshot per live-5 + 5 watermark advances.
# --------------------------------------------------------------------------- #


async def test_oi_tick_writes_one_snapshot_per_live5_and_advances_watermarks_atomically(
    session: Session, tmp_path: Path
) -> None:
    """Beh. 1: healthy tick → 1 snapshot per live-5, 5 watermark advances, all in one txn."""
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    snapshots = [_mk_oi_snapshot(sym) for sym in LIVE_5]
    adapter = FakeAdapter(oi_responses=list(snapshots))

    result = await async_oi_tick(
        adapter,  # type: ignore[arg-type]
        session,
        universe=LIVE_5,
        expected_utc=observed,
        observed_utc=observed,
        raw_root=tmp_path,
    )

    assert isinstance(result, OITickResult)
    assert result.snapshots_inserted == len(LIVE_5)
    assert result.watermarks_advanced == len(LIVE_5)
    assert result.gaps_recorded == 0

    # 5 watermark rows, one per symbol, all data_class='oi'.
    wms = (
        session.execute(select(CollectorWatermark).order_by(CollectorWatermark.symbol))
        .scalars()
        .all()
    )
    assert len(wms) == len(LIVE_5)
    for sym in LIVE_5:
        wm = next(w for w in wms if w.symbol == sym)
        assert wm.data_class == "oi"
        assert _epoch_ms(wm.last_tick_utc) == _epoch_ms(observed)

    # 5 Parquet snapshot files written, one per symbol.
    snapshot_files = sorted((tmp_path / "data_class=oi").rglob("*.parquet"))
    assert len(snapshot_files) == len(LIVE_5)

    # Adapter was called once per live-5 symbol.
    assert sorted(adapter.oi_calls) == sorted(LIVE_5)

    # No gap rows on the happy path.
    gaps = session.execute(select(CollectorGap)).scalars().all()
    assert len(gaps) == 0


# --------------------------------------------------------------------------- #
# Test 2 — adapter exception writes a gap row, no snapshot, no watermark.
# --------------------------------------------------------------------------- #


async def test_oi_tick_symbol_failure_records_per_symbol_gap_healthy_symbols_commit(
    session: Session, tmp_path: Path
) -> None:
    """Beh. 2 (per-symbol recovery): one bad symbol records its own gap row
    while healthy symbols still write snapshots + advance watermarks — a
    single delisted symbol must not blind the other four indefinitely."""
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    # LIVE_5 order is BTC, ETH, BNB, SOL, XRP — fail ETH mid-universe.
    oi_responses: list = [
        _mk_oi_snapshot("BTCUSDT"),
        RuntimeError("simulated Binance timeout"),
        _mk_oi_snapshot("BNBUSDT"),
        _mk_oi_snapshot("SOLUSDT"),
        _mk_oi_snapshot("XRPUSDT"),
    ]
    adapter = FakeAdapter(oi_responses=oi_responses)

    result = await async_oi_tick(
        adapter,  # type: ignore[arg-type]
        session,
        universe=LIVE_5,
        expected_utc=observed,
        observed_utc=observed,
        raw_root=tmp_path,
    )

    assert result.snapshots_inserted == 4
    assert result.watermarks_advanced == 4
    assert result.gaps_recorded == 1

    # Exactly one gap row, scoped to the failed symbol.
    gaps = session.execute(select(CollectorGap)).scalars().all()
    assert len(gaps) == 1
    assert gaps[0].symbol == "ETHUSDT"
    assert gaps[0].data_class == "oi"
    assert _epoch_ms(gaps[0].expected_utc) == _epoch_ms(observed)
    assert "simulated" in gaps[0].reason

    # Healthy symbols advanced; the failed one did not.
    wms = session.execute(select(CollectorWatermark)).scalars().all()
    assert {w.symbol for w in wms} == set(LIVE_5) - {"ETHUSDT"}

    # Snapshot files exist for healthy symbols only.
    snapshot_files = sorted((tmp_path / "data_class=oi").rglob("*.parquet"))
    assert len(snapshot_files) == 4


# --------------------------------------------------------------------------- #
# Test 3 — skipped scheduled tick records expected vs observed, no interpolation.
# --------------------------------------------------------------------------- #


async def test_oi_skipped_tick_records_expected_vs_observed_no_interpolation(
    session: Session, tmp_path: Path
) -> None:
    """Beh. 3: skipped tick records expected vs observed timestamps, no fabricated value.

    D-09: flag-never-fabricate. When the loop misses its scheduled tick
    (e.g. process restart), the caller signals `skip=True` and the
    collector writes an explicit gap row carrying both timestamps —
    downstream treats the gap as missing, NEVER as an interpolated zero.
    """
    expected = datetime(2026, 9, 19, 11, 55, tzinfo=UTC)  # when it SHOULD have run
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)  # when we noticed (5 min late)
    # No OI responses queued — adapter is never called on skip.
    adapter = FakeAdapter()

    result = await async_oi_tick(
        adapter,  # type: ignore[arg-type]
        session,
        universe=LIVE_5,
        expected_utc=expected,
        observed_utc=observed,
        raw_root=tmp_path,
        skip=True,
    )

    assert result.snapshots_inserted == 0
    assert result.watermarks_advanced == 0
    assert result.gaps_recorded == 1

    gaps = session.execute(select(CollectorGap)).scalars().all()
    assert len(gaps) == 1
    assert gaps[0].data_class == "oi"
    assert _epoch_ms(gaps[0].expected_utc) == _epoch_ms(expected)
    assert _epoch_ms(gaps[0].observed_utc) == _epoch_ms(observed)  # != expected — shows the lag
    assert gaps[0].expected_utc == _to_naive_utc(expected)
    assert gaps[0].observed_utc == _to_naive_utc(observed)
    assert "skip" in gaps[0].reason.lower()

    # No snapshot files for a skipped tick.
    snapshot_files = sorted((tmp_path / "data_class=oi").rglob("*.parquet"))
    assert len(snapshot_files) == 0


# --------------------------------------------------------------------------- #
# Test 4 — funding sweep uses separate partition + watermark namespace.
# --------------------------------------------------------------------------- #


async def test_funding_sweep_uses_separate_partition_and_watermark_namespace(
    session: Session, tmp_path: Path
) -> None:
    """Beh. 4: funding sweep writes to data_class='funding' namespace, distinct from 'oi'."""
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    funding_ticks = [_mk_funding_tick(sym) for sym in LIVE_5]
    adapter = FakeAdapter(funding_responses=[funding_ticks])

    result = await async_funding_sweep(
        adapter,  # type: ignore[arg-type]
        session,
        universe=LIVE_5,
        observed_utc=observed,
        raw_root=tmp_path,
        since_ms=0,
    )

    assert isinstance(result, FundingSweepResult)
    assert result.funding_inserted == len(LIVE_5)
    assert result.watermarks_advanced == len(LIVE_5)
    assert result.gaps_recorded == 0

    # Watermark rows use data_class='funding', NOT 'oi'.
    wms = (
        session.execute(select(CollectorWatermark).order_by(CollectorWatermark.symbol))
        .scalars()
        .all()
    )
    assert len(wms) == len(LIVE_5)
    for wm in wms:
        assert wm.data_class == "funding"
        assert wm.symbol in LIVE_5

    # Files written under the funding partition, NOT the oi partition.
    funding_files = sorted((tmp_path / "data_class=funding").rglob("*.parquet"))
    assert len(funding_files) == len(LIVE_5)

    oi_dir = tmp_path / "data_class=oi"
    assert not oi_dir.exists(), "funding sweep must NOT create the oi partition directory"


# --------------------------------------------------------------------------- #
# Test 5 — opportunistic openInterestHist harvest tagged as research-grade.
# --------------------------------------------------------------------------- #


async def test_open_interest_history_harvest_tagged_as_research_grade(
    session: Session, tmp_path: Path
) -> None:
    """Beh. 5: openInterestHist rows carry source='research' (vs canonical 'oi' rows).

    D-08: the opportunistic /futures/data/openInterestHist harvest is
    research-grade only — never the canonical forward source. The
    harvested rows go to a separate partition AND carry an explicit
    source tag, so downstream consumers (Phase 6/7) can distinguish
    canonical day-one snapshots from historical best-effort data.
    """
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)

    # Build historical snapshots with source='research'.
    hist_snapshots_by_symbol: dict[str, list[OiSnapshot]] = {}
    for sym in LIVE_5:
        hist_snapshots_by_symbol[sym] = [
            OiSnapshot(
                symbol=sym,
                observed_at_utc=datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
                open_interest=Decimal("10000"),
                source="research",
            )
        ]

    adapter = FakeAdapter(oi_hist_response=hist_snapshots_by_symbol)

    rows_inserted = await harvest_open_interest_history(
        adapter,  # type: ignore[arg-type]
        session,
        universe=LIVE_5,
        observed_utc=observed,
        raw_root=tmp_path,
        lookback_days=30,
    )

    assert rows_inserted == len(LIVE_5)

    # Harvest files live under a distinct partition (NOT data_class=oi).
    research_dir = tmp_path / "data_class=oi_research"
    assert research_dir.exists(), "research harvest partition directory must exist"
    research_files = sorted(research_dir.rglob("*.parquet"))
    assert len(research_files) == len(LIVE_5)

    canonical_dir = tmp_path / "data_class=oi"
    assert not canonical_dir.exists(), (
        "research harvest must NOT write to the canonical oi partition"
    )

    # The harvested rows carry source='research' (read back from disk).
    import polars as pl

    for sym in LIVE_5:
        # Pathlib glob matches the directory containing the symbol partition.
        sym_dir = next(
            (d for d in research_dir.iterdir() if d.name == f"symbol={sym}"),
            None,
        )
        assert sym_dir is not None, f"missing research partition for {sym}"
        sym_files = sorted(sym_dir.rglob("*.parquet"))
        assert sym_files, f"missing research file for {sym}"
        df = pl.concat([pl.read_parquet(f) for f in sym_files])
        sources = df["source"].unique().to_list()
        assert sources == ["research"], (
            f"{sym} research rows must carry source='research', got {sources}"
        )

    # The opportunistic hist call hit the adapter once per live-5 symbol.
    assert sorted(s for s, _, _ in adapter.oi_hist_calls) == sorted(LIVE_5)


def test_gap_pk_columns_are_not_null_under_postgres_dialect() -> None:
    """PG rejects NULL in PK columns — SQLite tolerates it and masked CR-04.

    Compiles every model table against the PostgreSQL dialect and asserts
    no primary-key column is nullable, so a future `nullable=True` PK
    regresses here instead of on the real database. Tick-wide gaps use
    the `TICK_WIDE_SYMBOL` sentinel, never NULL.
    """
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable
    from src.db.models import TICK_WIDE_SYMBOL

    assert TICK_WIDE_SYMBOL, "tick-wide gap sentinel must be a non-empty string"

    dialect = postgresql.dialect()
    for tbl in Base.metadata.sorted_tables:
        pk_names = {c.name for c in tbl.primary_key.columns}
        assert pk_names, f"{tbl.name} has no primary key"
        for col in tbl.columns:
            if col.name in pk_names:
                assert col.nullable is False, (
                    f"{tbl.name}.{col.name} is a nullable PK column — "
                    "PostgreSQL rejects NULL in PKs"
                )
        # The compiled PG DDL must agree (belt-and-braces against the ORM).
        ddl = str(CreateTable(tbl).compile(dialect=dialect))
        assert "CREATE TABLE" in ddl


# --------------------------------------------------------------------------- #
# Runner entrypoint (WR-06): one tick, healthcheck, module entrypoint.
# --------------------------------------------------------------------------- #


async def test_run_once_tick_publishes_snapshots_and_watermarks(
    session: Session, tmp_path: Path
) -> None:
    """The loop's unit of work: one OI tick + one funding sweep."""
    from src.data.collector import _run_once_tick

    snapshots = [_mk_oi_snapshot(sym) for sym in LIVE_5]
    ticks = [[_mk_funding_tick(sym)] for sym in LIVE_5]
    adapter = FakeAdapter(oi_responses=snapshots, funding_responses=ticks)
    observed = datetime(2026, 9, 19, 12, 5, tzinfo=UTC)

    oi, funding = await _run_once_tick(
        adapter,  # type: ignore[arg-type]
        session,
        universe=LIVE_5,
        raw_root=tmp_path,
        observed_utc=observed,
    )

    assert oi.snapshots_inserted == len(LIVE_5)
    assert oi.gaps_recorded == 0
    assert funding.funding_inserted == len(LIVE_5)
    assert funding.gaps_recorded == 0
    # Both watermark namespaces advanced.
    oi_marks = (
        session.execute(select(CollectorWatermark).where(CollectorWatermark.data_class == "oi"))
        .scalars()
        .all()
    )
    funding_marks = (
        session.execute(
            select(CollectorWatermark).where(CollectorWatermark.data_class == "funding")
        )
        .scalars()
        .all()
    )
    assert len(oi_marks) == len(LIVE_5)
    assert len(funding_marks) == len(LIVE_5)


def test_healthcheck_fails_without_watermarks(tmp_path: Path) -> None:
    """No OI tick ever completed → exit 1 (fail closed, not healthy)."""
    from src.data.collector import _check_health

    db_path = tmp_path / "health.db"
    url = f"sqlite:///{db_path}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()

    assert _check_health(url, universe=LIVE_5, max_age_seconds=600) == 1


def test_healthcheck_passes_with_fresh_watermarks(tmp_path: Path) -> None:
    """A recent tick per symbol → exit 0."""
    from src.data.collector import _check_health

    db_path = tmp_path / "health.db"
    url = f"sqlite:///{db_path}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    now = datetime.now(UTC)
    for sym in LIVE_5:
        for data_class in ("oi", "funding"):
            s.merge(
                CollectorWatermark(
                    symbol=sym,
                    data_class=data_class,
                    last_tick_utc=now,
                    updated_at_utc=now,
                )
            )
    s.commit()
    s.close()
    engine.dispose()

    assert _check_health(url, universe=LIVE_5, max_age_seconds=600) == 0


def test_healthcheck_fails_with_stale_funding(tmp_path: Path) -> None:
    """WR-01: fresh OI but stale funding → exit 1, not silently healthy.

    The funding wedge (one transient per-symbol failure stalling the
    whole funding sweep while OI keeps succeeding) must surface as
    UNHEALTHY instead of hiding behind the OI-only probe.
    """
    from datetime import timedelta

    from src.data.collector import _check_health

    db_path = tmp_path / "health.db"
    url = f"sqlite:///{db_path}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    now = datetime.now(UTC)
    for sym in LIVE_5:
        s.merge(
            CollectorWatermark(
                symbol=sym,
                data_class="oi",
                last_tick_utc=now,
                updated_at_utc=now,
            )
        )
        stale = now - timedelta(hours=10)
        s.merge(
            CollectorWatermark(
                symbol=sym,
                data_class="funding",
                last_tick_utc=stale,
                updated_at_utc=stale,
            )
        )
    s.commit()
    s.close()
    engine.dispose()

    assert _check_health(url, universe=LIVE_5, max_age_seconds=600) == 1


def test_collector_module_has_real_entrypoint() -> None:
    """`python -m src.data.collector --help` exits 0 (not import-and-exit)."""
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "src.data.collector", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    assert "--healthcheck" in proc.stdout
    assert "--once" in proc.stdout
    assert "--collect-list" in proc.stdout


# --------------------------------------------------------------------------- #
# WR-01 regression: per-symbol funding resume + idempotent retry.
# --------------------------------------------------------------------------- #


def _mk_funding_tick_at(symbol: str, ts: datetime, *, rate: str = "0.0001") -> FundingTick:
    """Build a funding tick for a specific funding timestamp."""
    return FundingTick(
        symbol=symbol,
        funding_time_utc=ts,
        funding_rate=Decimal(rate),
        mark_price=Decimal("50000.00"),
    )


async def test_funding_sweep_retry_after_transient_failure_makes_progress(
    session: Session, tmp_path: Path
) -> None:
    """WR-01: one transient per-symbol failure must not wedge later sweeps.

    Sweep 1: BTC fails (adapter error → gap row), ETH writes event E and
    advances. Sweep 2 (retry, BTC healthy again): per-symbol resume
    means ETH resumes from E+1 — its re-fetched E is skipped as
    already-covered instead of tripping the D-04 immutability guard —
    while BTC backfills its missed tick. Both watermarks converge; the
    sweep completes instead of raising FileExistsError forever.
    """
    universe = ["BTCUSDT", "ETHUSDT"]
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    event_e = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)
    adapter = FakeAdapter(
        funding_responses=[
            RuntimeError("simulated transient funding outage"),  # sweep 1 BTC
            [_mk_funding_tick_at("ETHUSDT", event_e)],  # sweep 1 ETH
            [_mk_funding_tick_at("BTCUSDT", event_e)],  # sweep 2 BTC retry
            [_mk_funding_tick_at("ETHUSDT", event_e)],  # sweep 2 ETH re-fetch
        ]
    )

    sweep1 = await async_funding_sweep(
        adapter,  # type: ignore[arg-type]
        session,
        universe=universe,
        observed_utc=observed,
        raw_root=tmp_path,
        since_ms=0,
    )
    assert sweep1.funding_inserted == 1
    assert sweep1.gaps_recorded == 1

    # The retry must complete (no FileExistsError), backfill BTC, and
    # skip ETH's already-covered re-fetch.
    sweep2 = await async_funding_sweep(
        adapter,  # type: ignore[arg-type]
        session,
        universe=universe,
        observed_utc=observed,
        raw_root=tmp_path,
        since_ms=0,
    )
    assert sweep2.funding_inserted == 1
    assert sweep2.gaps_recorded == 0
    assert sweep2.skipped_existing == 1

    # Per-symbol resume: BTC had no watermark → falls back to since_ms;
    # ETH resumes just after its own watermark, NOT the global minimum.
    btc_calls = [c for c in adapter.funding_calls if c[0] == "BTCUSDT"]
    eth_calls = [c for c in adapter.funding_calls if c[0] == "ETHUSDT"]
    assert btc_calls[1][1] == 0
    assert eth_calls[1][1] == int(event_e.timestamp() * 1000) + 1

    # Both watermarks converged on E; exactly 2 tick files on disk.
    wms = {
        w.symbol: w
        for w in session.execute(
            select(CollectorWatermark).where(CollectorWatermark.data_class == "funding")
        )
        .scalars()
        .all()
    }
    assert set(wms) == set(universe)
    assert _epoch_ms(wms["BTCUSDT"].last_tick_utc) == _epoch_ms(event_e)
    assert _epoch_ms(wms["ETHUSDT"].last_tick_utc) == _epoch_ms(event_e)
    assert len(sorted((tmp_path / "data_class=funding").rglob("*.parquet"))) == 2


async def test_funding_sweep_treats_existing_tick_file_as_covered(
    session: Session, tmp_path: Path
) -> None:
    """WR-01: a tick file already on disk is covered, not fatal.

    A prior sweep may have written the Parquet file and then rolled
    back its DB commit (non-transactional writes vs transactional
    watermarks diverge). The retry sees a stale watermark but an
    existing file: it must skip idempotently and advance the watermark
    past the on-disk tick instead of aborting the sweep.
    """
    from src.data.collector import _write_funding_tick

    observed = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    event_e = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)
    tick = _mk_funding_tick_at("BTCUSDT", event_e)
    _write_funding_tick(tick, tmp_path)  # orphaned Parquet, no watermark yet

    adapter = FakeAdapter(funding_responses=[[tick]])
    result = await async_funding_sweep(
        adapter,  # type: ignore[arg-type]
        session,
        universe=["BTCUSDT"],
        observed_utc=observed,
        raw_root=tmp_path,
        since_ms=0,
    )

    assert result.funding_inserted == 0
    assert result.skipped_existing == 1
    assert result.gaps_recorded == 0
    assert result.watermarks_advanced == 1
    wm = session.execute(
        select(CollectorWatermark).where(
            CollectorWatermark.symbol == "BTCUSDT",
            CollectorWatermark.data_class == "funding",
        )
    ).scalar_one_or_none()
    assert wm is not None
    assert _epoch_ms(wm.last_tick_utc) == _epoch_ms(event_e)


# --------------------------------------------------------------------------- #
# WR-01 mixed-watermark contract: fresh symbol's bootstrap is bounded even
# when another symbol's watermark is older than the bootstrap window.
# --------------------------------------------------------------------------- #


def test_funding_since_ms_fresh_symbol_uses_bounded_bootstrap_not_stale_min(
    session: Session,
) -> None:
    """WR-01: a fresh symbol's `since_ms` must be the bounded bootstrap
    window, NOT the stale watermark + 1 of another symbol.

    Pre-fix, `_funding_since_ms` returned `min(starts)` over all symbols,
    so a fresh symbol inherited the oldest watermarked symbol's
    `watermark + 1` — over-fetching (extra exchange weight, possible
    `limit=1000` truncation) on the first sweep. The fix returns the
    fresh-symbol bootstrap directly; watermarked symbols bypass the
    returned value via per-symbol resume in `async_funding_sweep`.
    """
    from src.data.collector import _funding_since_ms

    # BTC has a stale watermark (10h old — older than the 8h bootstrap).
    # ETH has no watermark (fresh deploy).
    stale = datetime(2026, 9, 19, 2, 0, tzinfo=UTC)  # 10h before observed
    session.merge(
        CollectorWatermark(
            symbol="BTCUSDT",
            data_class="funding",
            last_tick_utc=stale,
            updated_at_utc=stale,
        )
    )
    session.commit()

    observed = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    now_ms = int(observed.timestamp() * 1000)
    bootstrap_ms = 8 * 60 * 60_000  # FUNDING_BOOTSTRAP_LOOKBACK_MS

    since_ms = _funding_since_ms(session, ["BTCUSDT", "ETHUSDT"], now_ms)

    # Fresh symbol's bootstrap: now_ms - 8h, NOT stale_watermark + 1.
    assert since_ms == now_ms - bootstrap_ms
    # Sanity: the stale watermark + 1 would be ~2h earlier than the
    # bootstrap — the pre-fix bug would have returned that smaller value.
    stale_plus_one = int(stale.timestamp() * 1000) + 1
    assert since_ms > stale_plus_one, (
        "fresh symbol must NOT inherit the stale watermark + 1 "
        f"(stale+1={stale_plus_one}, got={since_ms})"
    )


async def test_funding_sweep_mixed_watermarks_fresh_symbol_uses_bounded_bootstrap(
    session: Session, tmp_path: Path
) -> None:
    """WR-01: end-to-end mixed-watermark contract.

    One stale watermark (BTC, 10h old) + one fresh symbol (ETH, no
    watermark). The fresh symbol's fetch `start_ms` must be the bounded
    bootstrap window (`now_ms - 8h`), NOT the stale watermark + 1.
    Locks the contract that `_funding_since_ms` returns the fresh-symbol
    fallback directly.
    """
    from datetime import timedelta

    from src.data.collector import _run_once_tick

    observed = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    stale = observed - timedelta(hours=10)
    session.merge(
        CollectorWatermark(
            symbol="BTCUSDT",
            data_class="funding",
            last_tick_utc=stale,
            updated_at_utc=stale,
        )
    )
    session.commit()

    # Adapter returns one tick per symbol; OI responses for both.
    oi_snapshots = [
        _mk_oi_snapshot("BTCUSDT"),
        _mk_oi_snapshot("ETHUSDT"),
    ]
    funding_ticks = [
        [_mk_funding_tick_at("BTCUSDT", observed - timedelta(hours=8))],
        [_mk_funding_tick_at("ETHUSDT", observed - timedelta(hours=8))],
    ]
    adapter = FakeAdapter(oi_responses=oi_snapshots, funding_responses=funding_ticks)

    await _run_once_tick(
        adapter,  # type: ignore[arg-type]
        session,
        universe=["BTCUSDT", "ETHUSDT"],
        raw_root=tmp_path,
        observed_utc=observed,
    )

    # BTC resumes from its own stale watermark + 1 (per-symbol resume).
    # ETH (fresh) uses the bounded bootstrap: now_ms - 8h.
    now_ms = int(observed.timestamp() * 1000)
    bootstrap_ms = 8 * 60 * 60_000
    expected_eth_start = now_ms - bootstrap_ms

    btc_calls = [c for c in adapter.funding_calls if c[0] == "BTCUSDT"]
    eth_calls = [c for c in adapter.funding_calls if c[0] == "ETHUSDT"]
    assert len(btc_calls) == 1
    assert len(eth_calls) == 1
    assert btc_calls[0][1] == int(stale.timestamp() * 1000) + 1
    assert eth_calls[0][1] == expected_eth_start, (
        f"fresh ETH must use bounded bootstrap {expected_eth_start}, got {eth_calls[0][1]}"
    )


# --------------------------------------------------------------------------- #
# Phase 13 plan 01 (D-01, D-02, F-107): the collector universe comes from the
# collect list, never from a hard-coded live-5 fallback.
# --------------------------------------------------------------------------- #

_COLLECT_EXTRAS = (
    "ADAUSDT",
    "AVAXUSDT",
    "DOGEUSDT",
    "DOTUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "MATICUSDT",
    "NEARUSDT",
    "SUIUSDT",
    "TRXUSDT",
    "UNIUSDT",
)


def _write_collect_list(path: Path, symbols: list[str]) -> Path:
    body = ", ".join(f'"{s}"' for s in symbols)
    lines = [
        'schema = "collect-list/1"',
        'list_id = "collect-list-v1"',
        'chosen_on = "2026-09-30"',
        'selection_rule = "test fixture"',
        "top_n = 15",
        f"symbols = [{body}]",
    ]
    path.write_text(os.linesep.join(lines) + os.linesep, encoding="utf-8")
    return path


def _sqlite_url(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'collector.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return url


def _install_fake_adapter(monkeypatch: pytest.MonkeyPatch, adapter: FakeAdapter) -> list[int]:
    """Patch the collector's adapter factory; returns a construction counter."""
    built: list[int] = []

    def factory() -> FakeAdapter:
        built.append(1)
        return adapter

    monkeypatch.setattr("src.data.collector.BinanceUsdmAdapter", factory)
    return built


def test_main_once_polls_exactly_the_collect_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.data.collector import main

    symbols = sorted([*LIVE_5, *_COLLECT_EXTRAS])
    assert len(symbols) == 16
    list_path = _write_collect_list(tmp_path / "list.toml", symbols)
    adapter = FakeAdapter(oi_responses=[_mk_oi_snapshot(s) for s in symbols])
    _install_fake_adapter(monkeypatch, adapter)

    rc = main(
        [
            "--once",
            "--collect-list",
            str(list_path),
            "--database-url",
            _sqlite_url(tmp_path),
            "--raw-root",
            str(tmp_path / "raw"),
        ]
    )

    assert rc == 0
    assert adapter.oi_calls == symbols


def test_missing_collect_list_refuses_start_without_live5_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from src.data.collector import main

    adapter = FakeAdapter(oi_responses=[_mk_oi_snapshot(s) for s in LIVE_5])
    built = _install_fake_adapter(monkeypatch, adapter)

    rc = main(
        [
            "--once",
            "--collect-list",
            str(tmp_path / "missing.toml"),
            "--database-url",
            _sqlite_url(tmp_path),
            "--raw-root",
            str(tmp_path / "raw"),
        ]
    )

    assert rc == 2
    assert "collect list" in capsys.readouterr().err
    assert built == []
    assert adapter.oi_calls == []
    assert adapter.funding_calls == []


def test_healthcheck_with_missing_collect_list_is_unhealthy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from src.data.collector import main

    rc = main(
        [
            "--healthcheck",
            "--collect-list",
            str(tmp_path / "missing.toml"),
            "--database-url",
            _sqlite_url(tmp_path),
        ]
    )

    assert rc == 1
    assert "collect list" in capsys.readouterr().err


def test_explicit_universe_override_is_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.data.collector import main

    override = ["BTCUSDT", "ETHUSDT"]
    adapter = FakeAdapter(oi_responses=[_mk_oi_snapshot(s) for s in override])
    _install_fake_adapter(monkeypatch, adapter)
    common = [
        "--once",
        "--collect-list",
        str(tmp_path / "ignored-missing.toml"),
        "--database-url",
        _sqlite_url(tmp_path),
        "--raw-root",
        str(tmp_path / "raw"),
    ]

    assert main([*common, "--universe", *override]) == 0
    assert adapter.oi_calls == override

    bad_adapter = FakeAdapter()
    _install_fake_adapter(monkeypatch, bad_adapter)
    assert main([*common, "--universe", "BTCUSDT", "../ETHUSDT"]) == 2
    assert bad_adapter.oi_calls == []


# --------------------------------------------------------------------------- #
# Phase 13 plan 01 (research Pitfall 5): the loop sleeps to the next cadence
# boundary so the period does not stretch by the tick duration.
# --------------------------------------------------------------------------- #


def test_ms_until_next_tick_on_boundary_waits_full_cadence() -> None:
    from src.data.collector import _ms_until_next_tick

    assert _ms_until_next_tick(12 * 3_600_000, 300_000) == 300_000


def test_ms_until_next_tick_mid_period() -> None:
    from src.data.collector import _ms_until_next_tick

    assert _ms_until_next_tick(12 * 3_600_000 + 300_000 + 7_250, 300_000) == 292_750


def test_ms_until_next_tick_after_overrun_does_not_replay_missed_boundary() -> None:
    from src.data.collector import _ms_until_next_tick

    # The tick ran 303 s; the boundary at +300 s is missed and not replayed.
    assert _ms_until_next_tick(12 * 3_600_000 + 303_000, 300_000) == 297_000


@pytest.mark.parametrize("bad", [0, -1, -300_000])
def test_ms_until_next_tick_rejects_non_positive_cadence(bad: int) -> None:
    from src.data.collector import _ms_until_next_tick

    with pytest.raises(ValueError, match="cadence"):
        _ms_until_next_tick(1_000, bad)


def test_loop_sleeps_to_next_cadence_boundary_after_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from src.data import collector

    list_path = _write_collect_list(tmp_path / "list.toml", list(LIVE_5))
    clock = iter(
        [
            datetime(2026, 9, 30, 12, 5, 0, 0, tzinfo=UTC),
            datetime(2026, 9, 30, 12, 5, 7, 250_000, tzinfo=UTC),
        ]
    )
    monkeypatch.setattr(collector, "_utc_now", lambda: next(clock))
    _install_fake_adapter(monkeypatch, FakeAdapter())

    async def fake_tick(*_args: object, **_kwargs: object) -> tuple[object, object]:
        return (
            SimpleNamespace(snapshots_inserted=0, gaps_recorded=0),
            SimpleNamespace(funding_inserted=0, gaps_recorded=0),
        )

    monkeypatch.setattr(collector, "_run_once_tick", fake_tick)
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise KeyboardInterrupt

    monkeypatch.setattr(collector.time, "sleep", fake_sleep)

    rc = collector.main(
        [
            "--collect-list",
            str(list_path),
            "--database-url",
            _sqlite_url(tmp_path),
            "--raw-root",
            str(tmp_path / "raw"),
        ]
    )

    assert rc == 0
    assert sleeps == [292.75]


# --------------------------------------------------------------------------- #
# Phase 13 plan 06 (D-23, DATA-02): paginated, resumable funding-history
# backfill. The fake serves one page per call from a queue (FakeAdapter) or
# filters a full history by start_ms like the exchange (PagedFundingAdapter).
# --------------------------------------------------------------------------- #

_FUNDING_EPOCH = datetime(2024, 1, 1, tzinfo=UTC)
_FAR_END_MS = int(datetime(2030, 1, 1, tzinfo=UTC).timestamp() * 1000)


def _funding_series(
    symbol: str, count: int, *, first_index: int = 0, mark: str | None = "50000.00"
) -> list[FundingTick]:
    """`count` funding ticks 8h apart starting `first_index` steps after epoch."""
    from datetime import timedelta

    return [
        FundingTick(
            symbol=symbol,
            funding_time_utc=_FUNDING_EPOCH + timedelta(hours=8 * (first_index + i)),
            funding_rate=Decimal("0.0001"),
            mark_price=Decimal(mark) if mark is not None else None,
        )
        for i in range(count)
    ]


class PagedFundingAdapter(FakeAdapter):
    """Serves each symbol's full history filtered by start_ms/end_ms/limit."""

    def __init__(self, history: dict[str, list[FundingTick]]) -> None:
        super().__init__()
        self._history = history

    async def funding_rate(
        self,
        symbol: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1000,
    ) -> list[FundingTick]:
        self.funding_calls.append((symbol, start_ms, end_ms))
        rows = self._history.get(symbol or "", [])
        picked = [
            t
            for t in rows
            if (start_ms is None or _epoch_ms(t.funding_time_utc) >= start_ms)
            and (end_ms is None or _epoch_ms(t.funding_time_utc) <= end_ms)
        ]
        return picked[:limit]


def _funding_files(root: Path) -> list[Path]:
    return sorted((root / "data_class=funding").rglob("*.parquet"))


async def test_funding_history_paginates_and_advances_watermark(
    session: Session, tmp_path: Path
) -> None:
    from src.data.collector import FundingHistoryResult, backfill_funding_history

    history = _funding_series("BTCUSDT", 2190)
    adapter = PagedFundingAdapter({"BTCUSDT": history})

    result = await backfill_funding_history(
        adapter,  # type: ignore[arg-type]
        session,
        symbols=["BTCUSDT"],
        start_ms=_epoch_ms(_FUNDING_EPOCH),
        end_ms=_FAR_END_MS,
        raw_root=tmp_path,
        observed_utc=datetime(2026, 9, 30, tzinfo=UTC),
        page_limit=1000,
        pace_seconds=0,
    )

    assert isinstance(result, FundingHistoryResult)
    assert result.rows_per_symbol == {"BTCUSDT": 2190}
    assert result.pages == 3
    assert result.gaps_recorded == 0
    assert result.truncated_symbols == ()
    assert len(_funding_files(tmp_path)) == 2190
    # A short third page ends the walk: exactly three calls, no empty fourth.
    assert len(adapter.funding_calls) == 3
    # The second call resumes 1 ms after the last funding time of page 1.
    assert adapter.funding_calls[1][1] == _epoch_ms(history[999].funding_time_utc) + 1
    wm = session.execute(
        select(CollectorWatermark).where(
            CollectorWatermark.symbol == "BTCUSDT",
            CollectorWatermark.data_class == "funding",
        )
    ).scalar_one()
    assert _epoch_ms(wm.last_tick_utc) == _epoch_ms(history[-1].funding_time_utc)


async def test_funding_history_rerun_writes_nothing_twice(session: Session, tmp_path: Path) -> None:
    from src.data.collector import backfill_funding_history

    history = _funding_series("BTCUSDT", 25)
    start_ms = _epoch_ms(_FUNDING_EPOCH)
    observed = datetime(2026, 9, 30, tzinfo=UTC)

    first = await backfill_funding_history(
        PagedFundingAdapter({"BTCUSDT": history}),  # type: ignore[arg-type]
        session,
        symbols=["BTCUSDT"],
        start_ms=start_ms,
        end_ms=_FAR_END_MS,
        raw_root=tmp_path,
        observed_utc=observed,
        page_limit=10,
        pace_seconds=0,
    )
    assert first.rows_per_symbol == {"BTCUSDT": 25}
    before = {p: p.stat().st_mtime_ns for p in _funding_files(tmp_path)}
    assert len(before) == 25

    # Re-run against an exchange-like adapter: every tick already has a file.
    second = await backfill_funding_history(
        PagedFundingAdapter({"BTCUSDT": history}),  # type: ignore[arg-type]
        session,
        symbols=["BTCUSDT"],
        start_ms=start_ms,
        end_ms=_FAR_END_MS,
        raw_root=tmp_path,
        observed_utc=observed,
        page_limit=10,
        pace_seconds=0,
    )
    assert second.rows_per_symbol == {"BTCUSDT": 0}
    assert second.gaps_recorded == 0

    # Re-run against a queue adapter that replays already covered ticks: the
    # existing files de-duplicate them on write, nothing raises and nothing is
    # rewritten.
    replay = FakeAdapter(funding_responses=[history[:10]])
    third = await backfill_funding_history(
        replay,  # type: ignore[arg-type]
        session,
        symbols=["BTCUSDT"],
        start_ms=start_ms,
        end_ms=_FAR_END_MS,
        raw_root=tmp_path,
        observed_utc=observed,
        page_limit=10,
        pace_seconds=0,
    )
    assert third.rows_per_symbol == {"BTCUSDT": 0}
    assert third.gaps_recorded == 0
    after = {p: p.stat().st_mtime_ns for p in _funding_files(tmp_path)}
    assert after == before


async def test_funding_history_ignores_a_live_sweep_watermark_at_now(
    session: Session, tmp_path: Path
) -> None:
    """CR-04: a collector that ran first leaves the shared watermark at "now".

    The history walk must still start at the dataset window, write every
    missing tick, de-duplicate the one the live sweep already wrote, and never
    move the watermark backwards.
    """
    from src.data.collector import _advance_watermark, _write_funding_tick, backfill_funding_history

    history = _funding_series("BTCUSDT", 25)
    live_tick = history[-1]
    _write_funding_tick(live_tick, tmp_path)  # what the live sweep stored
    _advance_watermark(
        session,
        symbol="BTCUSDT",
        data_class="funding",
        last_tick_utc=datetime(2026, 9, 30, tzinfo=UTC),
        updated_at_utc=datetime(2026, 9, 30, tzinfo=UTC),
    )
    session.commit()
    adapter = PagedFundingAdapter({"BTCUSDT": history})

    result = await backfill_funding_history(
        adapter,  # type: ignore[arg-type]
        session,
        symbols=["BTCUSDT"],
        start_ms=_epoch_ms(_FUNDING_EPOCH),
        end_ms=_FAR_END_MS,
        raw_root=tmp_path,
        observed_utc=datetime(2026, 9, 30, tzinfo=UTC),
        page_limit=10,
        pace_seconds=0,
    )

    assert adapter.funding_calls[0][1] == _epoch_ms(_FUNDING_EPOCH)
    assert result.rows_per_symbol == {"BTCUSDT": 24}
    assert len(_funding_files(tmp_path)) == 25
    wm = session.execute(
        select(CollectorWatermark).where(
            CollectorWatermark.symbol == "BTCUSDT",
            CollectorWatermark.data_class == "funding",
        )
    ).scalar_one()
    assert _epoch_ms(wm.last_tick_utc) == _epoch_ms(datetime(2026, 9, 30, tzinfo=UTC))


async def test_funding_history_null_mark_price_is_stored_as_null(
    session: Session, tmp_path: Path
) -> None:
    import polars as pl
    from src.data.collector import backfill_funding_history

    history = _funding_series("BTCUSDT", 2, mark=None)
    await backfill_funding_history(
        PagedFundingAdapter({"BTCUSDT": history}),  # type: ignore[arg-type]
        session,
        symbols=["BTCUSDT"],
        start_ms=_epoch_ms(_FUNDING_EPOCH),
        end_ms=_FAR_END_MS,
        raw_root=tmp_path,
        observed_utc=datetime(2026, 9, 30, tzinfo=UTC),
        pace_seconds=0,
    )

    files = _funding_files(tmp_path)
    assert len(files) == 2
    for path in files:
        frame = pl.read_parquet(path)
        assert frame["mark_price"].to_list() == [None]
        assert frame["funding_rate"].to_list() == [Decimal("0.0001000000")]


async def test_funding_history_isolates_failing_symbol(session: Session, tmp_path: Path) -> None:
    from src.data.collector import backfill_funding_history

    adapter = FakeAdapter(
        funding_responses=[
            RuntimeError("simulated outage"),
            _funding_series("ETHUSDT", 4),
        ]
    )

    result = await backfill_funding_history(
        adapter,  # type: ignore[arg-type]
        session,
        symbols=["BTCUSDT", "ETHUSDT"],
        start_ms=_epoch_ms(_FUNDING_EPOCH),
        end_ms=_FAR_END_MS,
        raw_root=tmp_path,
        observed_utc=datetime(2026, 9, 30, tzinfo=UTC),
        pace_seconds=0,
    )

    assert result.rows_per_symbol == {"BTCUSDT": 0, "ETHUSDT": 4}
    assert result.gaps_recorded == 1
    gaps = session.execute(select(CollectorGap)).scalars().all()
    assert len(gaps) == 1
    assert gaps[0].symbol == "BTCUSDT"
    assert gaps[0].data_class == "funding"
    assert gaps[0].reason.startswith("adapter_error:")
    wm_symbols = {
        w.symbol
        for w in session.execute(
            select(CollectorWatermark).where(CollectorWatermark.data_class == "funding")
        )
        .scalars()
        .all()
    }
    assert wm_symbols == {"ETHUSDT"}


async def test_funding_history_page_cap_is_reported(session: Session, tmp_path: Path) -> None:
    import structlog
    from src.data.collector import backfill_funding_history

    pages = [_funding_series("BTCUSDT", 3, first_index=3 * i) for i in range(6)]
    adapter = FakeAdapter(funding_responses=list(pages))

    with structlog.testing.capture_logs() as logs:
        result = await backfill_funding_history(
            adapter,  # type: ignore[arg-type]
            session,
            symbols=["BTCUSDT"],
            start_ms=_epoch_ms(_FUNDING_EPOCH),
            end_ms=_FAR_END_MS,
            raw_root=tmp_path,
            observed_utc=datetime(2026, 9, 30, tzinfo=UTC),
            page_limit=3,
            max_pages=2,
            pace_seconds=0,
        )

    assert len(adapter.funding_calls) == 2
    assert result.pages == 2
    assert result.rows_per_symbol == {"BTCUSDT": 6}
    assert result.truncated_symbols == ("BTCUSDT",)
    events = [entry["event"] for entry in logs]
    assert events.count("collector.funding_history.page") == 2
    assert "collector.funding_history.truncated" in events


# --------------------------------------------------------------------------- #
# Phase 13 plan 06 (F-408): tick writers publish atomically and never
# overwrite; a crash mid-write leaves neither a torn file nor a temp file.
# --------------------------------------------------------------------------- #


def _tick_writer_case(name: str) -> tuple[object, object]:
    from src.data import collector

    if name == "oi":
        return collector._write_oi_snapshot, _mk_oi_snapshot("BTCUSDT")
    if name == "oi_research":
        return collector._write_oi_research_snapshot, _mk_oi_snapshot("BTCUSDT")
    return collector._write_funding_tick, _mk_funding_tick("BTCUSDT")


@pytest.mark.parametrize("writer_name", ["oi", "oi_research", "funding"])
def test_tick_writers_are_atomic(
    writer_name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import polars as pl

    writer, tick = _tick_writer_case(writer_name)

    def _crash(self: pl.DataFrame, file: Path, *args: object, **kwargs: object) -> None:
        Path(file).write_bytes(b"PAR1-partial")
        raise OSError("simulated crash mid write")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", _crash)

    with pytest.raises(OSError, match="simulated crash"):
        writer(tick, tmp_path)  # type: ignore[operator]

    leftovers = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert leftovers == []


@pytest.mark.parametrize("writer_name", ["oi", "oi_research", "funding"])
def test_tick_writer_refuses_overwrite(writer_name: str, tmp_path: Path) -> None:
    writer, tick = _tick_writer_case(writer_name)

    path = writer(tick, tmp_path)  # type: ignore[operator]
    first_bytes = Path(path).read_bytes()

    with pytest.raises(FileExistsError):
        writer(tick, tmp_path)  # type: ignore[operator]

    assert Path(path).read_bytes() == first_bytes
    assert [p for p in Path(path).parent.iterdir()] == [Path(path)]


# --------------------------------------------------------------------------- #
# Phase 13 plan 06 (D-25, F-706): warn-only server-time probe at start. It
# only measures and logs; fail-closed clock checks belong to Phase 18.
# --------------------------------------------------------------------------- #

_PROBE_NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)


async def test_clock_probe_warns_on_large_offset() -> None:
    from datetime import timedelta

    import structlog
    from src.data.collector import _probe_server_clock

    adapter = FakeAdapter(server_time_response=_PROBE_NOW + timedelta(seconds=5))

    with structlog.testing.capture_logs() as logs:
        offset = await _probe_server_clock(
            adapter,  # type: ignore[arg-type]
            local_now=lambda: _PROBE_NOW,
        )

    assert offset == 5000
    entries = [e for e in logs if e["event"] == "collector.clock_offset"]
    assert len(entries) == 1
    assert entries[0]["log_level"] == "warning"
    assert entries[0]["offset_ms"] == 5000


async def test_clock_probe_small_offset_logs_info() -> None:
    from datetime import timedelta

    import structlog
    from src.data.collector import _probe_server_clock

    adapter = FakeAdapter(server_time_response=_PROBE_NOW + timedelta(milliseconds=200))

    with structlog.testing.capture_logs() as logs:
        offset = await _probe_server_clock(
            adapter,  # type: ignore[arg-type]
            local_now=lambda: _PROBE_NOW,
        )

    assert offset == 200
    entries = [e for e in logs if e["event"] == "collector.clock_offset"]
    assert len(entries) == 1
    assert entries[0]["log_level"] == "info"


async def test_clock_probe_negative_offset_beyond_threshold_warns() -> None:
    from datetime import timedelta

    import structlog
    from src.data.collector import _probe_server_clock

    adapter = FakeAdapter(server_time_response=_PROBE_NOW - timedelta(seconds=3))

    with structlog.testing.capture_logs() as logs:
        offset = await _probe_server_clock(
            adapter,  # type: ignore[arg-type]
            local_now=lambda: _PROBE_NOW,
        )

    assert offset == -3000
    assert [e["log_level"] for e in logs if e["event"] == "collector.clock_offset"] == ["warning"]


async def test_clock_probe_failure_never_blocks_start() -> None:
    import structlog
    from src.data.collector import _probe_server_clock

    adapter = FakeAdapter(server_time_response=RuntimeError("no route to host"))

    with structlog.testing.capture_logs() as logs:
        offset = await _probe_server_clock(
            adapter,  # type: ignore[arg-type]
            local_now=lambda: _PROBE_NOW,
        )

    assert offset is None
    entries = [e for e in logs if e["event"] == "collector.clock_probe_failed"]
    assert len(entries) == 1
    assert entries[0]["log_level"] == "warning"
    assert entries[0]["error_type"] == "RuntimeError"


def test_main_once_probes_clock_once_and_probe_failure_keeps_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.data.collector import main

    list_path = _write_collect_list(tmp_path / "list.toml", list(LIVE_5))

    def common(run: str) -> list[str]:
        # Separate raw root and database per run: the fixed snapshot time
        # would otherwise hit the D-04 no-overwrite guard on the second run.
        root = tmp_path / run
        root.mkdir()
        return [
            "--once",
            "--collect-list",
            str(list_path),
            "--database-url",
            _sqlite_url(root),
            "--raw-root",
            str(root / "raw"),
        ]

    healthy = FakeAdapter(oi_responses=[_mk_oi_snapshot(s) for s in LIVE_5])
    _install_fake_adapter(monkeypatch, healthy)
    assert main(common("healthy")) == 0
    assert healthy.server_time_calls == 1

    failing = FakeAdapter(
        oi_responses=[_mk_oi_snapshot(s) for s in LIVE_5],
        server_time_response=RuntimeError("time endpoint down"),
    )
    _install_fake_adapter(monkeypatch, failing)
    assert main(common("failing")) == 0
    assert failing.server_time_calls == 1
    assert sorted(failing.oi_calls) == sorted(LIVE_5)


def test_healthcheck_does_not_probe_clock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.data.collector import main

    list_path = _write_collect_list(tmp_path / "list.toml", list(LIVE_5))
    adapter = FakeAdapter()
    built = _install_fake_adapter(monkeypatch, adapter)

    main(
        [
            "--healthcheck",
            "--collect-list",
            str(list_path),
            "--database-url",
            _sqlite_url(tmp_path),
        ]
    )

    assert built == []
    assert adapter.server_time_calls == 0


def test_loop_probes_clock_once_before_first_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from src.data import collector

    list_path = _write_collect_list(tmp_path / "list.toml", list(LIVE_5))
    adapter = FakeAdapter()
    _install_fake_adapter(monkeypatch, adapter)
    order: list[str] = []

    original_probe = collector._probe_server_clock

    async def spy_probe(*args: object, **kwargs: object) -> int | None:
        order.append("probe")
        return await original_probe(*args, **kwargs)  # type: ignore[arg-type]

    async def fake_tick(*_args: object, **_kwargs: object) -> tuple[object, object]:
        order.append("tick")
        return (
            SimpleNamespace(snapshots_inserted=0, gaps_recorded=0),
            SimpleNamespace(funding_inserted=0, gaps_recorded=0),
        )

    def stop_sleep(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(collector, "_probe_server_clock", spy_probe)
    monkeypatch.setattr(collector, "_run_once_tick", fake_tick)
    monkeypatch.setattr(collector.time, "sleep", stop_sleep)

    rc = collector.main(
        [
            "--collect-list",
            str(list_path),
            "--database-url",
            _sqlite_url(tmp_path),
            "--raw-root",
            str(tmp_path / "raw"),
        ]
    )

    assert rc == 0
    assert order == ["probe", "tick"]
    assert adapter.server_time_calls == 1
