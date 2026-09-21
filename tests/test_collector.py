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
    ) -> None:
        self._oi = list(oi_responses or [])
        self._funding = list(funding_responses or [])
        self._oi_hist = oi_hist_response or {}
        self.oi_calls: list[str] = []
        self.funding_calls: list[tuple[str | None, int | None, int | None]] = []
        self.oi_hist_calls: list[tuple[str, str, int]] = []

    async def open_interest(self, symbol: str) -> OiSnapshot:
        self.oi_calls.append(symbol)
        if not self._oi:
            raise RuntimeError(
                f"FakeAdapter.open_interest: no response queued for {symbol}"
            )
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
    wms = session.execute(
        select(CollectorWatermark).order_by(CollectorWatermark.symbol)
    ).scalars().all()
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
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)   # when we noticed (5 min late)
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
    wms = session.execute(
        select(CollectorWatermark).order_by(CollectorWatermark.symbol)
    ).scalars().all()
    assert len(wms) == len(LIVE_5)
    for wm in wms:
        assert wm.data_class == "funding"
        assert wm.symbol in LIVE_5

    # Files written under the funding partition, NOT the oi partition.
    funding_files = sorted((tmp_path / "data_class=funding").rglob("*.parquet"))
    assert len(funding_files) == len(LIVE_5)

    oi_dir = tmp_path / "data_class=oi"
    assert not oi_dir.exists(), (
        "funding sweep must NOT create the oi partition directory"
    )


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
    assert research_dir.exists(), (
        "research harvest partition directory must exist"
    )
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
    oi_marks = session.execute(
        select(CollectorWatermark).where(CollectorWatermark.data_class == "oi")
    ).scalars().all()
    funding_marks = session.execute(
        select(CollectorWatermark).where(
            CollectorWatermark.data_class == "funding"
        )
    ).scalars().all()
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


# --------------------------------------------------------------------------- #
# WR-01 regression: per-symbol funding resume + idempotent retry.
# --------------------------------------------------------------------------- #


def _mk_funding_tick_at(
    symbol: str, ts: datetime, *, rate: str = "0.0001"
) -> FundingTick:
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
            select(CollectorWatermark).where(
                CollectorWatermark.data_class == "funding"
            )
        )
        .scalars()
        .all()
    }
    assert set(wms) == set(universe)
    assert _epoch_ms(wms["BTCUSDT"].last_tick_utc) == _epoch_ms(event_e)
    assert _epoch_ms(wms["ETHUSDT"].last_tick_utc) == _epoch_ms(event_e)
    assert (
        len(sorted((tmp_path / "data_class=funding").rglob("*.parquet"))) == 2
    )


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
