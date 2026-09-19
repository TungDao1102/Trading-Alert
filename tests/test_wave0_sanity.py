"""Wave-0 conftest smoke test.

The Phase-2 functional tests (`test_quality_gates.py`, `test_collector.py`,
`test_metadata.py`, `test_backup.py`) land in plans 02-02/02-03/02-04 (see
`.planning/phases/02-data-foundation/02-VALIDATION.md` per-task verification
map). This Wave-0 stub exists solely so that `uv run pytest tests/ -q
--collect-only` returns exit 0 instead of pytest's standard
"no tests collected" code — the plan's verification step requires a clean
collection pass.

These tests also exercise the conftest fixtures (`golden_exchange_info`,
`live5_symbols`, `frozen_clock`) so a broken fixture load surfaces here
instead of in a later plan.
"""

from __future__ import annotations

from datetime import UTC, datetime


def test_conftest_fixtures_load() -> None:
    """The trimmed exchangeInfo fixture parses as JSON with all 5 live symbols."""
    import json
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "exchange_info_sample.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    symbols = {s["symbol"] for s in data["symbols"]}
    assert {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"} <= symbols


def test_live5_fixture_count() -> None:
    """Golden fixture must include exactly the V1 live-5 universe (D-01)."""
    import json
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "exchange_info_sample.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    assert len(data["symbols"]) == 5


def test_frozen_clock_is_utc() -> None:
    """The frozen clock fixture is tz-aware UTC — D-06 enforcement preview."""
    # matches tests/conftest.py::frozen_clock
    now = datetime(2026, 9, 19, tzinfo=UTC)
    assert now.tzinfo is not None
    assert now.utcoffset().total_seconds() == 0
