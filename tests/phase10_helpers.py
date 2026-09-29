"""Shared helpers for the Phase 10 analytics tests (plan 10-01).

Fixture layout (`tests/fixtures/phase10/<case>/{input,expected}.json`) mirrors the
Phase 6 golden-fixture convention: hand-authored numbers, Decimals as strings,
datetimes as ISO-8601 with a `+00:00` suffix.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.analytics.lifecycle import LifecyclePath, LifecycleRecord
from src.analytics.types import EvidenceKind, TradeOutcome
from src.backtest.simulator import TradeRecord
from src.core.types import Candle
from src.paper.attribution import AttributionKind
from src.paper.journal import PaperRecord

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase10"

_DECIMAL_FIELDS = frozenset(
    {
        "entry_price",
        "quantity",
        "exit_price",
        "realized_pnl",
        "realized_risk",
        "gross_pnl",
        "entry_fee",
        "exit_fee",
        "funding_amount",
        "slippage_amount",
        "modeled_costs_per_unit",
    }
)
_DATETIME_FIELDS = frozenset({"entry_time_utc", "exit_time_utc"})

_TRADE_DEFAULTS: dict[str, Any] = {
    "trade_id": "T-DEFAULT",
    "signal_id": "SIG-DEFAULT",
    "trade_plan_id": "PLAN-DEFAULT",
    "strategy_version": "v2.0.0",
    "parameter_set_hash": "a" * 64,
    "symbol": "BTCUSDT",
    "direction": "LONG",
    "entry_kind": "ENTRY_FILLED",
    "entry_price": None,
    "entry_time_utc": None,
    "quantity": None,
    "exit_kind": None,
    "exit_price": None,
    "exit_time_utc": None,
    "realized_pnl": None,
    "realized_risk": None,
    "gross_pnl": None,
    "entry_fee": None,
    "exit_fee": None,
    "funding_amount": None,
    "slippage_amount": None,
    "modeled_costs_per_unit": None,
    "coverage_note": None,
    "fallback_applied": False,
    "outcome_kind": "OK",
    "reason_code": "OK",
}


def load_input(case: str) -> dict[str, Any]:
    """Load `tests/fixtures/phase10/<case>/input.json`."""
    loaded: dict[str, Any] = json.loads(
        (FIXTURES_DIR / case / "input.json").read_text(encoding="utf-8")
    )
    return loaded


def load_expected(case: str) -> dict[str, Any]:
    """Load `tests/fixtures/phase10/<case>/expected.json`."""
    loaded: dict[str, Any] = json.loads(
        (FIXTURES_DIR / case / "expected.json").read_text(encoding="utf-8")
    )
    return loaded


def parse_utc(iso: str) -> datetime:
    """Parse an ISO-8601 string into a UTC-aware datetime (naive input rejected)."""
    parsed = datetime.fromisoformat(iso)
    if parsed.tzinfo is None:
        raise ValueError(f"naive datetime in fixture: {iso!r}")
    return parsed.astimezone(UTC)


def D(value: str) -> Decimal:  # noqa: N802 - terse fixture helper
    """Build a Decimal from a string (never from a float)."""
    if not isinstance(value, str):
        raise TypeError(f"D() takes a str, got {type(value).__name__}")
    return Decimal(value)


def make_candle(symbol: str, open_time_utc: datetime, high: str, low: str) -> Candle:
    """Build a 1m candle whose open/close both equal the low (OHLC-range valid)."""
    low_d = D(low)
    return Candle(
        symbol=symbol,
        interval="1m",
        open_time_utc=open_time_utc,
        close_time_utc=open_time_utc + timedelta(seconds=59),
        open=low_d,
        high=D(high),
        low=low_d,
        close=low_d,
        volume=Decimal("1"),
    )


def make_candles(rows: list[dict[str, str]]) -> list[Candle]:
    """Build candles from fixture rows {symbol, open_time_utc, high, low}."""
    return [
        make_candle(row["symbol"], parse_utc(row["open_time_utc"]), row["high"], row["low"])
        for row in rows
    ]


def make_trade_record(**overrides: Any) -> TradeRecord:
    """Build a TradeRecord from a dict of JSON scalars (Decimals/datetimes parsed)."""
    fields: dict[str, Any] = dict(_TRADE_DEFAULTS)
    unknown = set(overrides) - set(fields)
    if unknown:
        raise KeyError(f"unknown TradeRecord fields: {sorted(unknown)}")
    for name, value in overrides.items():
        if value is not None and name in _DECIMAL_FIELDS:
            fields[name] = D(value)
        elif value is not None and name in _DATETIME_FIELDS:
            fields[name] = parse_utc(value)
        else:
            fields[name] = value
    return TradeRecord(**fields)


def make_paper_record(row: dict[str, Any]) -> PaperRecord:
    """Build a PaperRecord from a fixture row (attribution/ISO times parsed)."""
    fields = dict(row)
    fields["attribution"] = AttributionKind(fields["attribution"])
    for name in (
        "signal_detected_at_utc",
        "approval_acted_at_utc",
        "order_submitted_at_utc",
        "fill_time_utc",
    ):
        raw = fields[name]
        fields[name] = None if raw is None else parse_utc(raw)
    return PaperRecord(**fields)


def make_lifecycle_record(**overrides: Any) -> LifecycleRecord:
    """Build a LifecycleRecord; ISO strings become UTC datetimes, prices Decimals."""
    fields: dict[str, Any] = {
        "evidence": EvidenceKind.LIVE,
        "source_id": "SIG-DEFAULT",
        "signal_id": "SIG-DEFAULT",
        "symbol": "BTCUSDT",
        "strategy_version": "v2.0.0",
        "direction": "LONG",
        "path": LifecyclePath.SYSTEM_ONLY,
        "approval_result": None,
        "signal_detected_at_utc": None,
        "delivery_requested_at_utc": None,
        "approved_at_utc": None,
        "order_submitted_at_utc": None,
        "fill_time_utc": None,
        "intended_entry_price": None,
        "actual_entry_price": None,
        "entry_filled": None,
        "expired_without_fill": None,
        "reason_code": "",
        "synthetic_lag": False,
        "epoch_id": None,
    }
    unknown = set(overrides) - set(fields)
    if unknown:
        raise KeyError(f"unknown LifecycleRecord fields: {sorted(unknown)}")
    for name, value in overrides.items():
        if isinstance(value, str) and name.endswith("_utc"):
            fields[name] = parse_utc(value)
        elif isinstance(value, str) and name.endswith("_entry_price"):
            fields[name] = D(value)
        else:
            fields[name] = value
    return LifecycleRecord(**fields)


_OUTCOME_DEFAULTS: dict[str, Any] = {
    "evidence": EvidenceKind.BACKTEST,
    "trade_id": "T-DEFAULT",
    "signal_id": None,
    "strategy_version": "v2.0.0",
    "parameter_set_hash": "a" * 64,
    "symbol": "BTCUSDT",
    "direction": "LONG",
    "entry_kind": "ENTRY_FILLED",
    "entry_price": None,
    "entry_time_utc": None,
    "exit_kind": None,
    "exit_price": None,
    "exit_time_utc": None,
    "quantity": None,
    "realized_pnl": None,
    "realized_risk": None,
    "fallback_applied": False,
    "intended_entry_price": None,
    "regime": None,
    "vol_regime": None,
    "coverage_note": None,
}
_OUTCOME_DECIMALS = frozenset(
    {
        "entry_price",
        "exit_price",
        "quantity",
        "realized_pnl",
        "realized_risk",
        "intended_entry_price",
    }
)


def make_outcome(**overrides: Any) -> TradeOutcome:
    """Build a TradeOutcome from JSON scalars (Decimals/datetimes/evidence parsed)."""
    fields: dict[str, Any] = dict(_OUTCOME_DEFAULTS)
    unknown = set(overrides) - set(fields)
    if unknown:
        raise KeyError(f"unknown TradeOutcome fields: {sorted(unknown)}")
    for name, value in overrides.items():
        if value is not None and name in _OUTCOME_DECIMALS:
            fields[name] = D(value)
        elif value is not None and name in _DATETIME_FIELDS:
            fields[name] = parse_utc(value)
        elif name == "evidence" and isinstance(value, str):
            fields[name] = EvidenceKind(value)
        else:
            fields[name] = value
    return TradeOutcome(**fields)


def make_outcomes(rows: list[dict[str, Any]], **shared: Any) -> list[TradeOutcome]:
    """Build outcomes from fixture rows; `shared` overrides apply under each row."""
    return [make_outcome(**{**shared, **row}) for row in rows]
