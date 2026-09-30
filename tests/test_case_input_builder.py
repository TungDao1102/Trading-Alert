"""Tests for the Parquet -> backtest case-input builder (13-09, M4, D-17..D-22).

Every test publishes generated whole-day fixtures through the REAL immutable
publishers (`publish_batch`, `publish_mark_batch`) and the collector's tick
writers, so the builder reads exactly the layout production writes. The
module-scoped store is built once; tests that mutate a store work on a copy.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_usdm import FundingTick, Kline, MarkKline, OiSnapshot
from src.data import case_input as ci
from src.data.collector import _write_funding_tick, _write_oi_snapshot
from src.data.store import publish_batch, publish_mark_batch

SYMBOL = "BTCUSDT"
START = datetime(2026, 7, 1, tzinfo=UTC)
END = datetime(2026, 7, 4, tzinfo=UTC)
AS_OF = date(2026, 9, 30)
FIXTURES = Path(__file__).parent / "fixtures" / "phase6"

BAR_KEYS = {
    "symbol",
    "interval",
    "open_time_utc",
    "close_time_utc",
    "open",
    "high",
    "low",
    "close",
    "volume",
}

_STEP_MS = {"1m": 60_000, "1h": 3_600_000, "4h": 14_400_000}


def _price(open_ms: int) -> Decimal:
    return Decimal(100) + Decimal((open_ms // 60_000) % 97) / Decimal(100)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _kline(interval: str, open_ms: int) -> Kline:
    step = _STEP_MS[interval]
    p = _price(open_ms)
    return Kline(
        symbol=SYMBOL,
        interval=interval,
        open_time_utc=_from_ms(open_ms),
        close_time_utc=_from_ms(open_ms + step - 1),
        open=p,
        high=p + Decimal("0.05"),
        low=p - Decimal("0.05"),
        close=p,
        volume=Decimal("1.5"),
        quote_volume=p * Decimal("1.5"),
        trade_count=7,
    )


def _mark(open_ms: int) -> MarkKline:
    p = _price(open_ms)
    return MarkKline(
        symbol=SYMBOL,
        interval="1m",
        open_time_utc=_from_ms(open_ms),
        close_time_utc=_from_ms(open_ms + 59_999),
        open=p,
        high=p + Decimal("0.02"),
        low=p - Decimal("0.02"),
        close=p,
        price_tick_count=12,
    )


def _slots(start: datetime, end: datetime, interval: str) -> list[int]:
    step = _STEP_MS[interval]
    return list(range(_ms(start), _ms(end), step))


def build_store(raw_root: Path) -> None:
    """Publish three whole UTC days for BTCUSDT through the real writers."""
    for interval in ("1h", "4h", "1m"):
        publish_batch(
            [_kline(interval, ms) for ms in _slots(START, END, interval)],
            interval=interval,
            symbol=SYMBOL,
            raw_root=raw_root,
        )
    publish_mark_batch(
        [_mark(ms) for ms in _slots(START, END, "1m")],
        interval="1m",
        symbol=SYMBOL,
        raw_root=raw_root,
    )
    for ms in range(_ms(START), _ms(END), 8 * 3_600_000):
        _write_funding_tick(
            FundingTick(
                symbol=SYMBOL,
                funding_time_utc=_from_ms(ms),
                funding_rate=Decimal("0.0001"),
                mark_price=Decimal("100.50"),
            ),
            raw_root,
        )
    for ms in range(_ms(START), _ms(END), 300_000):
        _write_oi_snapshot(
            OiSnapshot(
                symbol=SYMBOL,
                observed_at_utc=_from_ms(ms),
                open_interest=Decimal("12345.5"),
            ),
            raw_root,
        )


@pytest.fixture(scope="module")
def base_store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("case_input_store") / "raw"
    build_store(root)
    return root


@pytest.fixture
def store(tmp_path: Path, base_store: Path) -> Path:
    """A private, mutable copy of the module store."""
    dest = tmp_path / "raw"
    shutil.copytree(base_store, dest)
    return dest


def _build(raw_root: Path, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "symbol": SYMBOL,
        "start_utc": START,
        "end_utc": END,
        "as_of_day_utc": AS_OF,
    }
    kwargs.update(overrides)
    return ci.build_case_input_data(raw_root, **kwargs)


def _scenario() -> dict[str, Any]:
    case = json.loads(
        (FIXTURES / "intrabar_both_touched" / "input.json").read_text(encoding="utf-8")
    )
    for key in ("strategy_bars", "context_bars", "intrabar_1m_map"):
        case.pop(key)
    return case


# --------------------------------------------------------------------------- #
# Task 1 - tracer: published Parquet -> builder -> simulator + assemble.
# --------------------------------------------------------------------------- #


def test_builder_reads_published_partitions(base_store: Path) -> None:
    data = _build(base_store)
    assert len(data.strategy_bars) == 72
    assert len(data.context_bars) == 18
    opens = [b["open_time_utc"] for b in data.strategy_bars]
    assert opens == sorted(opens)
    ctx_opens = [b["open_time_utc"] for b in data.context_bars]
    assert ctx_opens == sorted(ctx_opens)
    assert len(data.intrabar_1m_map) == 72
    for minutes in data.intrabar_1m_map.values():
        assert minutes is not None
        assert len(minutes) == 60
    assert len(data.mark_bars_1m) == 4320
    assert len(data.funding) == 9
    assert len(data.open_interest) == 864
    assert re.fullmatch(r"[0-9a-f]{64}", data.dataset_id)
    assert data.allowed_gaps == ()


def test_bar_dicts_are_string_typed_and_keys_match_close_time(base_store: Path) -> None:
    data = _build(base_store)
    for bar in (*data.strategy_bars, *data.context_bars):
        assert set(bar) == BAR_KEYS
        assert all(isinstance(v, str) for v in bar.values())
        # ISO timestamps, tz-aware UTC.
        assert datetime.fromisoformat(bar["open_time_utc"]).utcoffset() == timedelta(0)
    for bar, key in zip(data.strategy_bars, data.intrabar_1m_map, strict=True):
        assert key == f"BTCUSDT|{bar['close_time_utc']}"
    for minutes in data.intrabar_1m_map.values():
        assert minutes is not None
        for minute in minutes:
            assert set(minute) == BAR_KEYS
            assert minute["interval"] == "1m"
    # Decimal values are plain (never scientific) strings.
    first = data.strategy_bars[0]
    assert Decimal(first["open"]) == _price(_ms(START))
    assert "E" not in first["open"].upper()


def test_builder_output_runs_through_simulator_and_assemble(base_store: Path) -> None:
    from src.backtest.costs import build_cost_model
    from src.backtest.experiment import assemble
    from src.backtest.simulator import run

    data = _build(base_store)
    case = data.to_case_input(**_scenario())
    assert case["dataset_id"] == data.dataset_id
    assert len(case["strategy_bars"]) == 72
    result = run(case)
    assert "trades" in result

    identity = json.loads(
        (FIXTURES / "registry_identity" / "input.json").read_text(encoding="utf-8")
    )
    cost = dict(identity["cost_model"])
    cost["partial_fill_fraction"] = "0.5"
    record = assemble(
        parameter_set_id="baseline-v3",
        strategy_id=identity["strategy_id"],
        strategy_version=identity["strategy_version"],
        data_snapshot_id=data.dataset_id,
        code_version="13-09-test",
        cost_model=build_cost_model(cost),
        time_range_start_utc=data.start_utc,
        time_range_end_utc=data.end_utc,
        universe=[SYMBOL],
        run_type="CANDIDATE",
    )
    assert record.data_snapshot_id == data.dataset_id


def test_to_case_input_refuses_builder_key_collision(base_store: Path) -> None:
    data = _build(base_store)
    with pytest.raises(ci.CaseInputError):
        data.to_case_input(strategy_bars=[], **_scenario())
