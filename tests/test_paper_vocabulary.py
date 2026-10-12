"""Shared paper-runtime vocabulary (Phase 16, plan 16-08, D-05 / D-06).

The vocabulary is a pure module: source tags, health states, gap and drop reason codes,
runtime event types, the tagged bar and the gap record. No network is touched.
"""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

_T = datetime(2026, 10, 7, 8, 59, 59, 999000, tzinfo=UTC)


def _bar_kwargs() -> dict[str, object]:
    return {
        "symbol": "BTCUSDT",
        "interval": "1h",
        "open_time_utc": datetime(2026, 10, 7, 8, 0, tzinfo=UTC),
        "close_time_utc": _T,
        "open": Decimal("84094.70"),
        "high": Decimal("84139.20"),
        "low": Decimal("83902.50"),
        "close": Decimal("83909.90"),
        "volume": Decimal("5844.590"),
    }


def test_interval_ms_equals_the_data_layer_helper() -> None:
    """Drift guard: the vocabulary table equals the data-layer helper for the live intervals.

    The test may import the data layer; the vocabulary module itself may not.
    """
    from src.data.backfill import interval_ms
    from src.paper.vocabulary import INTERVAL_MS

    for interval in ("1m", "1h", "4h"):
        assert INTERVAL_MS[interval] == interval_ms(interval)


def test_vocabulary_module_imports_nothing_from_adapters_or_the_data_layer() -> None:
    source = Path("src/paper/vocabulary.py").read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert not [m for m in imported if m.startswith(("src.adapters", "src.data", "binance"))]


def test_runtime_event_type_carries_the_tick_stats_record() -> None:
    """One PAPER_TICK_STATS record per consumer iteration is written by plan 16-26."""
    from src.paper.vocabulary import RuntimeEventType

    assert RuntimeEventType.PAPER_TICK_STATS == "PAPER_TICK_STATS"
    names = {member.name for member in RuntimeEventType}
    assert {
        "RUNTIME_START",
        "RUNTIME_STOP",
        "EPOCH_PINNED",
        "PAPER_BAR_PROCESSED",
        "PAPER_GAP",
        "PAPER_TICK_STATS",
        "PAPER_REPLAY_INPUTS",
        "PAPER_HISTORY_BARS",
        "WS_DISCONNECT",
        "WS_RECONNECT",
        "HEALTH_STATE_CHANGED",
    } == names


def test_drop_reason_carries_future_close() -> None:
    """A closed event whose close time is later than the tick time (clock skew, research P20)."""
    from src.paper.vocabulary import DropReason

    assert DropReason.FUTURE_CLOSE == "FUTURE_CLOSE"


def test_source_tags_health_states_and_gap_reasons() -> None:
    from src.paper.vocabulary import GapReason, HealthState, SourceTag

    assert {m.name for m in SourceTag} == {"LIVE_WS", "REST_WARMUP", "REST_BACKFILL"}
    assert {m.name for m in HealthState} == {"HEALTHY", "DEGRADED", "DISCONNECTED"}
    assert {m.name for m in GapReason} == {
        "PROCESS_DOWN",
        "WS_DISCONNECTED",
        "WS_RECONNECT_WINDOW",
        "PLANNED_RESTART",
        "CRASH",
        "MAINTENANCE",
        "EXCHANGE_NO_CANDLE",
        "UNKNOWN",
    }


def test_tagged_bar_is_frozen_and_keeps_decimal_prices() -> None:
    from src.paper.vocabulary import SourceTag, TaggedBar

    bar = TaggedBar(source=SourceTag.LIVE_WS, **_bar_kwargs())  # type: ignore[arg-type]
    assert bar.open == Decimal("84094.70")
    assert bar.source is SourceTag.LIVE_WS
    with pytest.raises(FrozenInstanceError):
        bar.close = Decimal("1")  # type: ignore[misc]


def test_tagged_bar_rejects_a_naive_timestamp() -> None:
    from src.paper.vocabulary import SourceTag, TaggedBar

    kwargs = _bar_kwargs()
    kwargs["close_time_utc"] = datetime(2026, 10, 7, 8, 59, 59)
    with pytest.raises(ValueError, match="UTC-aware"):
        TaggedBar(source=SourceTag.LIVE_WS, **kwargs)  # type: ignore[arg-type]


def test_gap_record_is_frozen_and_rejects_a_naive_timestamp() -> None:
    from src.paper.vocabulary import GapReason, GapRecord

    gap = GapRecord(
        symbol="BTCUSDT",
        interval="1h",
        expected_close_utc=_T,
        reason=GapReason.WS_RECONNECT_WINDOW,
        detected_at_utc=_T,
    )
    assert gap.reason is GapReason.WS_RECONNECT_WINDOW
    with pytest.raises(FrozenInstanceError):
        gap.reason = GapReason.UNKNOWN  # type: ignore[misc]
    with pytest.raises(ValueError, match="UTC-aware"):
        GapRecord(
            symbol="BTCUSDT",
            interval="1h",
            expected_close_utc=datetime(2026, 10, 7, 8, 59, 59),
            reason=GapReason.UNKNOWN,
            detected_at_utc=_T,
        )
