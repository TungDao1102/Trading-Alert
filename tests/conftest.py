"""Shared pytest fixtures — Phase 2 Wave 0.

Per PATTERNS §17 + TESTING_STRATEGY §2 (golden-fixture model):
  - `golden_exchange_info`   — trimmed live-5 snapshot from /fapi/v1/exchangeInfo
  - `frozen_clock`           — returns 2026-09-19 UTC; injected into collectors
                               so gap-never-fabricate tests don't depend on wall-clock
  - `live5_symbols`          — D-01 universe (BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT)

Phase-2 task: tests/test_quality_gates.py + tests/test_collector.py will land
in plan 02-02 (DATA-01/DATA-02 tests). This conftest scaffolds the fixtures
they'll import so the migration + ORM commit ships a green test collection.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
EXCHANGE_INFO_FIXTURE = FIXTURES_DIR / "exchange_info_sample.json"

# D-01 — V1 live-5 universe, locked.
LIVE_5: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")


@pytest.fixture(scope="session")
def golden_exchange_info() -> dict:
    """Load the trimmed exchangeInfo snapshot (live-5). Recorded 2026-09-19."""
    return json.loads(EXCHANGE_INFO_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def live5_symbols() -> tuple[str, ...]:
    """D-01 universe — every Phase-2 collector + backfill targets these."""
    return LIVE_5


@pytest.fixture
def frozen_clock() -> datetime:
    """Frozen UTC clock — `2026-09-19T00:00:00Z`.

    Tests must inject this into any code path that would otherwise call
    `datetime.now(timezone.utc)` (collectors, watermark advance, gap journal).
    """
    return datetime(2026, 9, 19, tzinfo=UTC)


@pytest.fixture
def fixture_path() -> Iterator[Path]:
    """Convenience: yield the fixtures directory for ad-hoc JSON loads."""
    assert FIXTURES_DIR.is_dir(), f"missing fixtures dir: {FIXTURES_DIR}"
    yield FIXTURES_DIR
