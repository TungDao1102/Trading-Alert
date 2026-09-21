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
        assert wm.last_tick_utc == observed

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


async def test_oi_tick_adapter_exception_writes_gap_row_no_snapshot_no_watermark(
    session: Session, tmp_path: Path
) -> None:
    """Beh. 2: adapter raises → 1 gap row written, no snapshots, no watermark advance."""
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    adapter = FakeAdapter(oi_responses=[RuntimeError("simulated Binance timeout")])

    result = await async_oi_tick(
        adapter,  # type: ignore[arg-type]
        session,
        universe=LIVE_5,
        expected_utc=observed,
        observed_utc=observed,
        raw_root=tmp_path,
    )

    assert result.snapshots_inserted == 0
    assert result.watermarks_advanced == 0
    assert result.gaps_recorded == 1

    # Exactly one gap row, no watermark rows.
    gaps = session.execute(select(CollectorGap)).scalars().all()
    assert len(gaps) == 1
    assert gaps[0].data_class == "oi"
    assert gaps[0].expected_utc == observed
    assert "simulated" in gaps[0].reason

    wms = session.execute(select(CollectorWatermark)).scalars().all()
    assert len(wms) == 0

    # No snapshot files written on the failure path.
    snapshot_files = sorted((tmp_path / "data_class=oi").rglob("*.parquet"))
    assert len(snapshot_files) == 0


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
    assert gaps[0].expected_utc == expected
    assert gaps[0].observed_utc == observed  # != expected — shows the lag
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
        sym_files = sorted(research_dir.rglob(f"*symbol={sym}*.parquet"))
        assert sym_files, f"missing research file for {sym}"
        df = pl.concat([pl.read_parquet(f) for f in sym_files])
        sources = df["source"].unique().to_list()
        assert sources == ["research"], (
            f"{sym} research rows must carry source='research', got {sources}"
        )

    # The opportunistic hist call hit the adapter once per live-5 symbol.
    assert sorted(s for s, _, _ in adapter.oi_hist_calls) == sorted(LIVE_5)
