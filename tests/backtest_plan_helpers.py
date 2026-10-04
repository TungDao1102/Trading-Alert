"""Shared hand-built plan, minute and record helpers for Phase 14 tests (plan 14-01).

Every later Phase 14 plan builds its lifecycle, validator and golden cases on these
three factories so no test re-derives a plan or a minute by hand. All numbers are
built from strings, never from floats.

- `make_trade_plan`: a valid `TradePlan` with `take_profit_json` in the planner shape
  (keys tp1, tp2, tp1_role, tp2_role; see `src/core/planner.py`) and an
  `invalidation_rule_json` of `{"basis": "CANDLE_CLOSE", "level", "break_distance_atr"}`.
- `make_minute`: one 1m `Candle`, trade-price (volume 1) or mark-price (volume 0).
- `make_record`: a valid filled v2 `TradeRecord` with keyword overrides.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from src.backtest.records import TradeRecord
from src.core.types import Candle
from src.domain.enums import TradePlanStatus
from src.domain.trade_plan import TradePlan

SIGNAL_CLOSE = datetime(2026, 1, 5, 9, 59, 59, 999000, tzinfo=UTC)

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
        "planned_quantity",
        "tp1_quantity",
        "tp1_price",
    }
)
_DATETIME_FIELDS = frozenset(
    {
        "entry_time_utc",
        "exit_time_utc",
        "signal_close_utc",
        "tp1_time_utc",
        "resolved_at_utc",
    }
)


def D(value: str) -> Decimal:  # noqa: N802 - terse fixture helper
    """Build a Decimal from a string (never from a float)."""
    if not isinstance(value, str):
        raise TypeError(f"D() takes a str, got {type(value).__name__}")
    return Decimal(value)


def make_trade_plan(
    direction: str = "LONG",
    entry_min: str = "99.00",
    entry_max: str = "101.00",
    stop_loss: str = "98.00",
    tp1: str = "104.00",
    tp2: str = "108.00",
    signal_close_utc: datetime = SIGNAL_CLOSE,
    expiry_hours: int = 4,
    invalidation_level: str | None = None,
    *,
    break_distance_atr: str = "0.5",
    trade_plan_id: str = "tp-1",
    signal_id: str = "sig-1",
    quantity: str = "0.5",
    risk_budget: str = "1.50",
) -> TradePlan:
    """Build a valid hand-made `TradePlan` created at `signal_close_utc`.

    A `TradePlan` carries no side, so `direction` is only validated here (a typo cannot
    reach the lifecycle); the geometry comes from the prices the caller passes. The
    invalidation level defaults to the stop (D-35: the CANDLE_CLOSE level is the plan's
    own `stop_loss_price`).
    """
    if direction not in ("LONG", "SHORT"):
        raise ValueError(f"direction must be LONG or SHORT, got {direction!r}")
    level = stop_loss if invalidation_level is None else invalidation_level
    take_profit_json = json.dumps(
        {"tp1": tp1, "tp2": tp2, "tp1_role": "TAKE_PROFIT_1", "tp2_role": "TAKE_PROFIT_2"},
        sort_keys=True,
        separators=(",", ":"),
    )
    invalidation_rule_json = json.dumps(
        {"basis": "CANDLE_CLOSE", "level": level, "break_distance_atr": break_distance_atr},
        sort_keys=True,
        separators=(",", ":"),
    )
    return TradePlan(
        trade_plan_id=trade_plan_id,
        signal_id=signal_id,
        trade_plan_version="v1",
        entry_model="LIMIT_ZONE",
        entry_min_price=D(entry_min),
        entry_max_price=D(entry_max),
        stop_loss_price=D(stop_loss),
        take_profit_json=take_profit_json,
        invalidation_rule_json=invalidation_rule_json,
        expiry_utc=signal_close_utc + timedelta(hours=expiry_hours),
        expected_rr_json='{"tp1_rr":"2","tp2_rr":"4"}',
        risk_rate=D("0.01"),
        risk_budget=D(risk_budget),
        suggested_quantity=D(quantity),
        quantity_before_rounding=D(quantity),
        quantity_after_rounding=D(quantity),
        quantization_decision="ACCEPTED",
        plan_hash="a" * 64,
        status=TradePlanStatus.READY,
        created_at_utc=signal_close_utc,
    )


def make_minute(
    symbol: str,
    open_time_utc: datetime,
    open: str,
    high: str,
    low: str,
    close: str,
    kind: str,
    millisecond_close: bool = True,
) -> Candle:
    """Build one 1m candle. `kind` is "trade" (volume 1) or "mark" (volume 0).

    The close time is `open + 59.999 s` (the live convention) or `open + 59 s`
    (second-resolution fixtures) per `millisecond_close`.
    """
    if kind not in ("trade", "mark"):
        raise ValueError(f"kind must be 'trade' or 'mark', got {kind!r}")
    close_offset = timedelta(seconds=59, milliseconds=999 if millisecond_close else 0)
    return Candle(
        symbol=symbol,
        interval="1m",
        open_time_utc=open_time_utc,
        close_time_utc=open_time_utc + close_offset,
        open=D(open),
        high=D(high),
        low=D(low),
        close=D(close),
        volume=D("1") if kind == "trade" else D("0"),
    )


def _valid_record_fields() -> dict[str, Any]:
    return {
        "trade_id": "t" * 64,
        "signal_id": "sig-1",
        "trade_plan_id": "tp-1",
        "strategy_version": "v1",
        "parameter_set_hash": "b" * 64,
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entry_kind": "ENTRY_FILLED",
        "entry_price": D("100.00"),
        "entry_time_utc": datetime(2026, 1, 5, 10, 1, 59, 999000, tzinfo=UTC),
        "quantity": D("0.5"),
        "exit_kind": "SL",
        "exit_price": D("98.00"),
        "exit_time_utc": datetime(2026, 1, 5, 10, 30, 59, 999000, tzinfo=UTC),
        "realized_pnl": D("-1.0741"),
        "realized_risk": D("1.50"),
        "gross_pnl": D("-1.00"),
        "entry_fee": D("0.0200"),
        "exit_fee": D("0.0196"),
        "funding_amount": D("0"),
        "slippage_amount": D("0.0345"),
        "modeled_costs_per_unit": None,
        "coverage_note": None,
        "fallback_applied": False,
        "outcome_kind": "OK",
        "reason_code": "OK",
        "signal_close_utc": SIGNAL_CLOSE,
        "planned_quantity": D("0.5"),
        "resolved_at_utc": datetime(2026, 1, 5, 10, 30, 59, 999000, tzinfo=UTC),
    }


def make_record(**overrides: Any) -> TradeRecord:
    """Build a valid filled LONG `TradeRecord`, then apply keyword overrides.

    String overrides for Decimal fields become `Decimal`, ISO-string overrides for
    datetime fields become aware datetimes; anything else (including `None`) is set
    as given. Unknown field names raise `KeyError`.
    """
    fields = _valid_record_fields()
    known = {f.name for f in dataclasses.fields(TradeRecord)}
    unknown = set(overrides) - known
    if unknown:
        raise KeyError(f"unknown TradeRecord fields: {sorted(unknown)}")
    for name, value in overrides.items():
        if isinstance(value, str) and name in _DECIMAL_FIELDS:
            fields[name] = D(value)
        elif isinstance(value, str) and name in _DATETIME_FIELDS:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                raise ValueError(f"naive datetime for {name}: {value!r}")
            fields[name] = parsed.astimezone(UTC)
        else:
            fields[name] = value
    return TradeRecord(**fields)
