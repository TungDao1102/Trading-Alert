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

Phase-4 additions (plan 04-01):
  - `phase4_candles`         — 1H + 4H closed candles for the tracer slice
  - `phase4_parameters`      — pinned registry set (trend-pullback/baseline-v1)
  - `phase4_expected_features` — byte-exact expected feature values
  - `phase4_expected_signals` — byte-exact expected signals
  - `phase4_expected_plans`  — byte-exact expected plans
"""

from __future__ import annotations

import csv
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import structlog
from src.ops import redaction

from tests import infra_helpers

# pytest discovers fixtures by name in this module's namespace, so the
# Phase 17 disposable-database fixtures are imported (not used) here.
from tests.pg_support import (  # noqa: F401
    pg_db,
    pg_empty_db,
    pg_server_url,
    pg_template_name,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
EXCHANGE_INFO_FIXTURE = FIXTURES_DIR / "exchange_info_sample.json"

# Phase 3 fixtures directory (D-07).
PHASE3_FIXTURES_DIR = FIXTURES_DIR / "phase3"

# Phase 4 fixtures directory (plan 04-01).
PHASE4_FIXTURES_DIR = FIXTURES_DIR / "phase4"

# Phase 5 fixtures directory (plan 05-01, D-02 parity-fixture rule).
PHASE5_FIXTURES_DIR = FIXTURES_DIR / "phase5"

# D-01 — V1 live-5 universe, locked.
LIVE_5: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Gate ``docker``-marked tests on a reachable daemon (13.1-01).

    Skips with an explicit reason locally; FAILS under ``TRADING_CI_STRICT=1`` so CI can
    never pass vacuously. Looked up through the module so tests can monkeypatch the probe.
    """
    if item.get_closest_marker("docker") is None:
        return
    reachable, detail = infra_helpers.docker_daemon_reachable()
    if not reachable:
        infra_helpers.infra_skip(f"docker daemon not reachable: {detail}")


@pytest.fixture(autouse=True)
def _restore_logging_state() -> Iterator[None]:
    """Undo ``configure_logging`` side effects after every test (13.1-04).

    ``collector.main`` and ``backfill_cli.main`` call ``configure_logging()``; without this
    a test running ``main()`` would change structlog, the root logger, the excepthooks and the
    httpx levels for every later test.
    """
    was_configured = structlog.is_configured()
    structlog_config = structlog.get_config()
    root = logging.getLogger()
    handlers = list(root.handlers)
    handler_filters = {handler: list(handler.filters) for handler in handlers}
    root_filters = list(root.filters)
    root_level = root.level
    http_levels = {name: logging.getLogger(name).level for name in ("httpx", "httpcore")}
    yield
    redaction.uninstall_global_hooks()
    if was_configured:
        structlog.configure(**structlog_config)
    else:
        structlog.reset_defaults()
    for handler in list(root.handlers):
        if handler not in handler_filters:
            root.removeHandler(handler)
    for handler, filters in handler_filters.items():
        handler.filters[:] = filters
    root.filters[:] = root_filters
    root.setLevel(root_level)
    for name, level in http_levels.items():
        logging.getLogger(name).setLevel(level)


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
    return json.loads((PHASE3_FIXTURES_DIR / "parameters.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def phase3_expected_signals() -> dict:
    """Load the byte-exact expected signals (placeholder per D-09)."""
    return json.loads((PHASE3_FIXTURES_DIR / "expected_signals.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def phase3_expected_plans() -> dict:
    """Load the byte-exact expected plans (placeholder per D-09)."""
    return json.loads((PHASE3_FIXTURES_DIR / "expected_plans.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Phase 4 fixtures (plan 04-01, D-05/D-07/D-09).
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def phase4_candles() -> list[dict]:
    """Load the hand-built 1H + 4H closed candle CSV for the tracer slice.

    Columns per TESTING_STRATEGY §2:
    symbol,timeframe,open_time_utc,open,high,low,close,volume
    """
    with (PHASE4_FIXTURES_DIR / "candles.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="session")
def phase4_parameters() -> dict:
    """Load the pinned registry set (trend-pullback/baseline-v1)."""
    return json.loads((PHASE4_FIXTURES_DIR / "parameters.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def phase4_expected_features() -> dict:
    """Load the byte-exact expected feature values for the tracer slice."""
    return json.loads((PHASE4_FIXTURES_DIR / "expected_features.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def phase4_expected_signals() -> dict:
    """Load the byte-exact expected signals for the tracer slice."""
    return json.loads((PHASE4_FIXTURES_DIR / "expected_signals.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def phase4_expected_plans() -> dict:
    """Load the byte-exact expected plans for the tracer slice."""
    return json.loads((PHASE4_FIXTURES_DIR / "expected_plans.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Phase 5 fixtures (plan 05-01, D-02 parity-fixture rule).
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def phase5_parity_cases() -> list[dict]:
    """Load every parity case under tests/fixtures/phase5/.

    Each case directory contains `input.json` + `expected.json`. The
    list order is sorted by case name for deterministic iteration.
    """
    cases: list[dict] = []
    for case_dir in sorted(PHASE5_FIXTURES_DIR.iterdir()):
        if not case_dir.is_dir():
            continue
        cases.append(
            {
                "name": case_dir.name,
                "input": json.loads((case_dir / "input.json").read_text(encoding="utf-8")),
                "expected": json.loads((case_dir / "expected.json").read_text(encoding="utf-8")),
            }
        )
    return cases


@pytest.fixture
def phase5_frozen_clock() -> datetime:
    """Frozen UTC clock for parity fixtures — 2026-09-19T00:00:00Z."""
    return datetime(2026, 9, 19, tzinfo=UTC)
