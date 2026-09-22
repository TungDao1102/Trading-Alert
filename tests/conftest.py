"""Shared pytest fixtures — Phase 2 Wave 0 + Phase 3 extensions.

Per PATTERNS §17 + TESTING_STRATEGY §2 (golden-fixture model):
  - `golden_exchange_info`   — trimmed live-5 snapshot from /fapi/v1/exchangeInfo
  - `frozen_clock`           — returns 2026-09-19 UTC; injected into collectors
                               so gap-never-fabricate tests don't depend on wall-clock
  - `live5_symbols`          — D-01 universe (BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT)

Phase-3 additions (plan 03-01):
  - `phase3_candles`         — hand-built boundary-covering candle CSV
  - `phase3_parameters`      — pinned registry set
  - `phase3_expected_signals` — byte-exact expected signals (placeholder)
  - `phase3_expected_plans`  — byte-exact expected plans (placeholder)
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
EXCHANGE_INFO_FIXTURE = FIXTURES_DIR / "exchange_info_sample.json"

# Phase 3 fixtures directory (D-07).
PHASE3_FIXTURES_DIR = FIXTURES_DIR / "phase3"

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


# --------------------------------------------------------------------------- #
# Phase 3 fixtures (plan 03-01, D-07/D-09).
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def phase3_candles() -> list[dict]:
    """Load the hand-built boundary-covering candle CSV.

    Columns per TESTING_STRATEGY §2:
    symbol,timeframe,open_time_utc,open,high,low,close,volume
    """
    with (PHASE3_FIXTURES_DIR / "candles.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="session")
def phase3_parameters() -> dict:
    """Load the pinned registry set."""
    return json.loads(
        (PHASE3_FIXTURES_DIR / "parameters.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="session")
def phase3_expected_signals() -> dict:
    """Load the byte-exact expected signals (placeholder per D-09)."""
    return json.loads(
        (PHASE3_FIXTURES_DIR / "expected_signals.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="session")
def phase3_expected_plans() -> dict:
    """Load the byte-exact expected plans (placeholder per D-09)."""
    return json.loads(
        (PHASE3_FIXTURES_DIR / "expected_plans.json").read_text(encoding="utf-8")
    )
