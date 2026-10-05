"""Case-input v2 contract and parser (Phase 14, plan 14-08, D-31, D-34, D-36).

`parse_case_input` turns a JSON-like case dict into a frozen `ParsedCase`, failing closed
on anything it does not recognise. The contract (`case_input_schema` = "backtest-case/2"):

    strategy_id, strategy_version, parameter_set_id   registry identity (strings)
    symbols                  unique `^[A-Z0-9]+USDT$` symbols (any order; sorted on parse)
    strategy_bars            1h rows: symbol, interval, open/close time, OHLCV (strings)
    context_bars             4h rows, same shape
    trade_bars_1m, mark_bars_1m
                             1m rows, optional only when a `minute_source` is passed to the
                             engine (a passed source wins; the rows are then not read)
    funding                  rows: symbol, funding_time_utc, funding_rate, mark_price|null
    constraint_history       rows: symbol, metadata_observed_at_utc, price_tick_size,
                             quantity_step_size, min_quantity, min_notional
    account_state            equity, risk_rate
    cost_model               the registry cost slice; it must carry funding_convention
    data_window              start_utc, end_utc
    allowed_gaps             list of {series, symbol, start_utc, end_utc, missing}
    dataset_id               optional 64-hex dataset identity
    scripted_plans           optional list of {symbol, bar_close_utc, signal_id, direction,
                             entry_min_price, entry_max_price, stop_loss_price, tp1, tp2,
                             expiry_hours, [invalidation_level]}; its presence switches the
                             engine to the scripted front-end

The v1 keys in `REMOVED_V1_KEYS` are refused with a message naming them (the v1 fixture
shape carries a fixture clock, a single constraint snapshot and a per-bar intrabar map,
none of which exists in v2). A float anywhere, a naive datetime and an unknown key are
refused. Minute rows are never sorted silently: they pass through `ListMinuteSource`
validation, which rejects a decreasing, duplicated or overlapping series.

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic: stdlib + Decimal + the pure `src` core only.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from src.core._decimal import _mul
from src.core.types import AccountState, Candle
from src.domain.canonical import sha256_hex
from src.domain.enums import TradePlanStatus
from src.domain.ids import derive_child_id
from src.domain.trade_plan import TradePlan

from .constraints import ConstraintHistory, parse_constraint_row
from .costs import CostModel, build_cost_model
from .funding import FundingRow, parse_funding_row
from .series import ListMinuteSource, MinuteSource, parse_minute_row

CASE_INPUT_SCHEMA = "backtest-case/2"

# v1 keys: a fixture clock, one constraint snapshot, a per-bar intrabar map. Refused by name.
REMOVED_V1_KEYS: tuple[str, ...] = (
    "intrabar_1m_map",
    "constraint_snapshot",
    "open_positions",
    "daily_loss_quote",
    "now_utc",
    "ttl_seconds",
    "mark_price_bars",
)

REQUIRED_KEYS: tuple[str, ...] = (
    "case_input_schema",
    "strategy_id",
    "strategy_version",
    "parameter_set_id",
    "symbols",
    "strategy_bars",
    "context_bars",
    "funding",
    "constraint_history",
    "account_state",
    "cost_model",
    "data_window",
    "allowed_gaps",
)
OPTIONAL_KEYS: tuple[str, ...] = ("trade_bars_1m", "mark_bars_1m", "dataset_id", "scripted_plans")

STRATEGY_INTERVAL = "1h"
CONTEXT_INTERVAL = "4h"
FUNDING_SERIES = "funding"

_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+USDT$")
_HEX64_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_DIRECTIONS = frozenset({"LONG", "SHORT"})
_BAR_KEYS = frozenset(
    {
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
)
_GAP_KEYS = frozenset({"series", "symbol", "start_utc", "end_utc", "missing"})
_SCRIPTED_REQUIRED = frozenset(
    {
        "symbol",
        "bar_close_utc",
        "signal_id",
        "direction",
        "entry_min_price",
        "entry_max_price",
        "stop_loss_price",
        "tp1",
        "tp2",
        "expiry_hours",
    }
)
_SCRIPTED_KEYS = _SCRIPTED_REQUIRED | {"invalidation_level", "regime"}
_ZERO = Decimal("0")


@dataclass(frozen=True)
class AllowedGap:
    """An explicitly allowed data hole (D-36): a series, a symbol and a UTC interval."""

    series: str
    symbol: str
    start_utc: datetime
    end_utc: datetime
    missing: int | str


@dataclass(frozen=True)
class ScriptedPlan:
    """One hand-built plan scheduled at a strategy-bar close (fixtures only)."""

    symbol: str
    bar_close_utc: datetime
    signal_id: str
    direction: str
    plan: TradePlan
    regime: str | None = None


@dataclass(frozen=True)
class ParsedCase:
    """A validated case-input v2. Rows are frozen values; nothing is mutated after parse."""

    strategy_id: str
    strategy_version: str
    parameter_set_id: str
    symbols: tuple[str, ...]
    strategy_bars: tuple[Candle, ...]
    context_bars: tuple[Candle, ...]
    minute_source: MinuteSource | None
    funding_rows: tuple[FundingRow, ...]
    constraints: ConstraintHistory
    account_state: AccountState
    cost_model: CostModel
    data_start_utc: datetime
    data_end_utc: datetime
    allowed_gaps: tuple[AllowedGap, ...]
    dataset_id: str | None
    scripted_plans: tuple[ScriptedPlan, ...] | None


def _reject_floats(value: object, path: str) -> None:
    """Refuse a float anywhere in the case (money and rates are strings or ints, D-12)."""
    if isinstance(value, float):
        raise TypeError(f"{path} must not be a float (use a decimal string), got {value!r}")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_floats(item, f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _reject_floats(item, f"{path}[{index}]")


def _require_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object, got {type(value).__name__}")
    return value


def _require_list(value: object, name: str) -> Sequence[Any]:
    if not isinstance(value, list | tuple):
        raise TypeError(f"{name} must be a list, got {type(value).__name__}")
    return value


def _require_str(value: object, name: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{name} must be a non-empty string, got {value!r}")
    return value


def _check_keys(
    row: Mapping[str, Any], *, required: frozenset[str], allowed: frozenset[str], name: str
) -> None:
    missing = sorted(required - set(row))
    if missing:
        raise ValueError(f"{name} is missing keys {missing}")
    unknown = sorted(set(row) - allowed)
    if unknown:
        raise ValueError(f"{name} has unknown keys {unknown}")


def _utc(raw: object, name: str) -> datetime:
    """Parse an ISO-8601 string into a UTC-aware datetime; a naive time is refused."""
    if not isinstance(raw, str):
        raise TypeError(f"{name} must be an ISO-8601 string, got {type(raw).__name__}")
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"{name} is not an ISO-8601 timestamp: {raw!r}") from None
    if value.tzinfo is None:
        raise ValueError(f"{name} must be UTC-aware, got naive datetime {raw!r}")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC, got offset {value.utcoffset()} in {raw!r}")
    return value


def _decimal(raw: object, name: str) -> Decimal:
    """Parse a decimal string (or int) into a finite Decimal; floats and bools are refused."""
    if isinstance(raw, bool | float):
        raise TypeError(f"{name} must be a decimal string, got {type(raw).__name__}")
    if isinstance(raw, Decimal):
        value = raw
    elif isinstance(raw, int | str):
        try:
            value = Decimal(raw)
        except InvalidOperation:
            raise ValueError(f"{name} is not a decimal: {raw!r}") from None
    else:
        raise TypeError(f"{name} must be a decimal string, got {type(raw).__name__}")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite, got {raw!r}")
    return value


def _symbols(raw: object) -> tuple[str, ...]:
    items = _require_list(raw, "symbols")
    if not items:
        raise ValueError("symbols must not be empty")
    for symbol in items:
        if not isinstance(symbol, str) or not _SYMBOL_PATTERN.fullmatch(symbol):
            raise ValueError(f"symbol {symbol!r} does not match ^[A-Z0-9]+USDT$")
    if len(set(items)) != len(items):
        raise ValueError(f"symbols must be unique, got {list(items)}")
    return tuple(sorted(items))


def _parse_bars(
    raw: object, *, name: str, interval: str, symbols: tuple[str, ...]
) -> tuple[Candle, ...]:
    """Parse strategy or context rows; sort by `(close_time, symbol)`; refuse duplicates."""
    candles: list[Candle] = []
    for index, item in enumerate(_require_list(raw, name)):
        label = f"{name}[{index}]"
        row = _require_mapping(item, label)
        _check_keys(row, required=_BAR_KEYS, allowed=_BAR_KEYS, name=label)
        symbol = _require_str(row["symbol"], f"{label}.symbol")
        if symbol not in symbols:
            raise ValueError(f"{label}.symbol {symbol!r} is not in symbols {list(symbols)}")
        if row["interval"] != interval:
            raise ValueError(f"{label}.interval must be {interval!r}, got {row['interval']!r}")
        candles.append(
            Candle(
                symbol=symbol,
                interval=interval,
                open_time_utc=_utc(row["open_time_utc"], f"{label}.open_time_utc"),
                close_time_utc=_utc(row["close_time_utc"], f"{label}.close_time_utc"),
                open=_decimal(row["open"], f"{label}.open"),
                high=_decimal(row["high"], f"{label}.high"),
                low=_decimal(row["low"], f"{label}.low"),
                close=_decimal(row["close"], f"{label}.close"),
                volume=_decimal(row["volume"], f"{label}.volume"),
            )
        )
    candles.sort(key=lambda c: (c.close_time_utc, c.symbol))
    for earlier, later in zip(candles, candles[1:], strict=False):
        if (earlier.close_time_utc, earlier.symbol) == (later.close_time_utc, later.symbol):
            raise ValueError(
                f"{name} has a duplicate bar for {later.symbol} closing "
                f"{later.close_time_utc.isoformat()}"
            )
    return tuple(candles)


def _parse_minutes(
    raw: object, *, name: str, kind: str, symbols: tuple[str, ...]
) -> dict[str, list[Any]]:
    """Group minute rows by symbol keeping their order; ListMinuteSource validates the series."""
    grouped: dict[str, list[Any]] = {}
    for index, item in enumerate(_require_list(raw, name)):
        label = f"{name}[{index}]"
        row = _require_mapping(item, label)
        candle = parse_minute_row(row, kind=kind)
        if candle.symbol not in symbols:
            raise ValueError(f"{label}.symbol {candle.symbol!r} is not in symbols {list(symbols)}")
        grouped.setdefault(candle.symbol, []).append(candle)
    return grouped


def _parse_funding(raw: object, symbols: tuple[str, ...]) -> tuple[FundingRow, ...]:
    rows: list[FundingRow] = []
    for index, item in enumerate(_require_list(raw, "funding")):
        row = parse_funding_row(_require_mapping(item, f"funding[{index}]"))
        if row.symbol not in symbols:
            raise ValueError(f"funding[{index}].symbol {row.symbol!r} is not in symbols")
        rows.append(row)
    seen: set[tuple[str, datetime]] = set()
    for row in rows:
        key = (row.symbol, row.funding_time_utc)
        if key in seen:
            raise ValueError(
                f"duplicate funding_time_utc {row.funding_time_utc.isoformat()} for {row.symbol}"
            )
        seen.add(key)
    return tuple(sorted(rows, key=lambda r: (r.symbol, r.funding_time_utc)))


def _parse_constraints(raw: object, symbols: tuple[str, ...]) -> ConstraintHistory:
    rows = [
        parse_constraint_row(_require_mapping(item, f"constraint_history[{index}]"))
        for index, item in enumerate(_require_list(raw, "constraint_history"))
    ]
    history = ConstraintHistory.from_rows(rows)
    for symbol in history.rows_by_symbol:
        if symbol not in symbols:
            raise ValueError(f"constraint_history has rows for {symbol!r}, not in symbols")
    for symbol in symbols:
        if symbol not in history.rows_by_symbol:
            raise ValueError(f"constraint_history has no row for {symbol!r}")
    return history


def _parse_account(raw: object) -> AccountState:
    row = _require_mapping(raw, "account_state")
    _check_keys(
        row,
        required=frozenset({"equity", "risk_rate"}),
        allowed=frozenset({"equity", "risk_rate"}),
        name="account_state",
    )
    return AccountState(
        equity=_decimal(row["equity"], "account_state.equity"),
        risk_rate=_decimal(row["risk_rate"], "account_state.risk_rate"),
    )


def _parse_cost_model(raw: object) -> CostModel:
    row = _require_mapping(raw, "cost_model")
    if "funding_convention" not in row:
        raise ValueError(
            "cost_model must carry funding_convention (the funding sign convention is part "
            "of cost identity, D-16, D-36)"
        )
    try:
        return build_cost_model(dict(row))
    except KeyError as exc:
        raise ValueError(f"cost_model is missing key {exc}") from None


def _parse_window(raw: object) -> tuple[datetime, datetime]:
    row = _require_mapping(raw, "data_window")
    _check_keys(
        row,
        required=frozenset({"start_utc", "end_utc"}),
        allowed=frozenset({"start_utc", "end_utc"}),
        name="data_window",
    )
    start = _utc(row["start_utc"], "data_window.start_utc")
    end = _utc(row["end_utc"], "data_window.end_utc")
    if end <= start:
        raise ValueError("data_window.end_utc must be after data_window.start_utc")
    return start, end


def _parse_gaps(raw: object, symbols: tuple[str, ...]) -> tuple[AllowedGap, ...]:
    gaps: list[AllowedGap] = []
    for index, item in enumerate(_require_list(raw, "allowed_gaps")):
        label = f"allowed_gaps[{index}]"
        row = _require_mapping(item, label)
        _check_keys(row, required=_GAP_KEYS, allowed=_GAP_KEYS, name=label)
        symbol = _require_str(row["symbol"], f"{label}.symbol")
        if symbol not in symbols:
            raise ValueError(f"{label}.symbol {symbol!r} is not in symbols")
        missing = row["missing"]
        if isinstance(missing, bool) or not isinstance(missing, int | str):
            raise TypeError(f"{label}.missing must be an int or a string, got {missing!r}")
        start = _utc(row["start_utc"], f"{label}.start_utc")
        end = _utc(row["end_utc"], f"{label}.end_utc")
        if end < start:
            raise ValueError(f"{label}.end_utc must not be before start_utc")
        gaps.append(
            AllowedGap(
                series=_require_str(row["series"], f"{label}.series"),
                symbol=symbol,
                start_utc=start,
                end_utc=end,
                missing=missing,
            )
        )
    return tuple(gaps)


def _expiry_hours(raw: object, name: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int | str):
        raise TypeError(f"{name} must be a whole number of hours, got {raw!r}")
    try:
        hours = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number of hours, got {raw!r}") from None
    if hours <= 0:
        raise ValueError(f"{name} must be > 0, got {hours}")
    return hours


def _scripted_trade_plan(
    *,
    signal_id: str,
    direction: str,
    created_at_utc: datetime,
    row: Mapping[str, Any],
    label: str,
    account: AccountState,
) -> TradePlan:
    """Build the plan of a scripted row: planner-shaped JSON, zero-sized quantity placeholders.

    The risk function sizes the plan; the quantities stored on the plan are placeholders and
    never read. The id is derived from the signal like the planner does.
    """
    entry_min = _decimal(row["entry_min_price"], f"{label}.entry_min_price")
    entry_max = _decimal(row["entry_max_price"], f"{label}.entry_max_price")
    stop = _decimal(row["stop_loss_price"], f"{label}.stop_loss_price")
    tp1 = _decimal(row["tp1"], f"{label}.tp1")
    tp2 = _decimal(row["tp2"], f"{label}.tp2")
    level = (
        _decimal(row["invalidation_level"], f"{label}.invalidation_level")
        if "invalidation_level" in row
        else stop
    )
    hours = _expiry_hours(row["expiry_hours"], f"{label}.expiry_hours")
    take_profit_json = json.dumps(
        {
            "tp1": str(tp1),
            "tp2": str(tp2),
            "tp1_role": "TAKE_PROFIT_1",
            "tp2_role": "TAKE_PROFIT_2",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    invalidation_rule_json = json.dumps(
        {"basis": "CANDLE_CLOSE", "level": str(level), "break_distance_atr": "0"},
        sort_keys=True,
        separators=(",", ":"),
    )
    expiry_utc = created_at_utc + timedelta(hours=hours)
    plan_hash = sha256_hex(
        {
            "signal_id": signal_id,
            "direction": direction,
            "entry_min_price": entry_min,
            "entry_max_price": entry_max,
            "stop_loss_price": stop,
            "take_profit_json": take_profit_json,
            "invalidation_rule_json": invalidation_rule_json,
            "expiry_utc": expiry_utc,
            "created_at_utc": created_at_utc,
        }
    )
    return TradePlan(
        trade_plan_id=derive_child_id(signal_id, "trade_plan:v1"),
        signal_id=signal_id,
        trade_plan_version="v1",
        entry_model="LIMIT_ZONE",
        entry_min_price=entry_min,
        entry_max_price=entry_max,
        stop_loss_price=stop,
        take_profit_json=take_profit_json,
        invalidation_rule_json=invalidation_rule_json,
        expiry_utc=expiry_utc,
        expected_rr_json="{}",
        risk_rate=account.risk_rate,
        risk_budget=_mul(account.equity, account.risk_rate),
        suggested_quantity=_ZERO,
        quantity_before_rounding=_ZERO,
        quantity_after_rounding=_ZERO,
        quantization_decision="UNSIZED",
        plan_hash=plan_hash,
        status=TradePlanStatus.READY,
        created_at_utc=created_at_utc,
    )


def _parse_scripted(
    raw: object, symbols: tuple[str, ...], account: AccountState
) -> tuple[ScriptedPlan, ...]:
    plans: list[ScriptedPlan] = []
    for index, item in enumerate(_require_list(raw, "scripted_plans")):
        label = f"scripted_plans[{index}]"
        row = _require_mapping(item, label)
        _check_keys(row, required=_SCRIPTED_REQUIRED, allowed=_SCRIPTED_KEYS, name=label)
        symbol = _require_str(row["symbol"], f"{label}.symbol")
        if symbol not in symbols:
            raise ValueError(f"{label}.symbol {symbol!r} is not in symbols")
        direction = row["direction"]
        if direction not in _DIRECTIONS:
            raise ValueError(f"{label}.direction must be LONG or SHORT, got {direction!r}")
        signal_id = _require_str(row["signal_id"], f"{label}.signal_id")
        bar_close = _utc(row["bar_close_utc"], f"{label}.bar_close_utc")
        plan = _scripted_trade_plan(
            signal_id=signal_id,
            direction=direction,
            created_at_utc=bar_close,
            row=row,
            label=label,
            account=account,
        )
        regime = _require_str(row["regime"], f"{label}.regime") if "regime" in row else None
        plans.append(
            ScriptedPlan(
                symbol=symbol,
                bar_close_utc=bar_close,
                signal_id=signal_id,
                direction=direction,
                plan=plan,
                regime=regime,
            )
        )
    plans.sort(key=lambda p: (p.bar_close_utc, p.symbol))
    for earlier, later in zip(plans, plans[1:], strict=False):
        if (earlier.bar_close_utc, earlier.symbol) == (later.bar_close_utc, later.symbol):
            raise ValueError(
                f"two scripted plans for {later.symbol} at {later.bar_close_utc.isoformat()}"
            )
    return tuple(plans)


def parse_case_input(case_input: Mapping[str, Any]) -> ParsedCase:
    """Validate and parse a case-input v2 dict (fail closed on any defect).

    Raises:
        ValueError: a removed v1 key, a missing or wrong schema literal, an unknown or
            missing key, a naive datetime, a cost model without `funding_convention`, a
            symbol outside `symbols`, or any malformed row.
        TypeError: a float anywhere in the case, or a value of the wrong type.
    """
    case = _require_mapping(case_input, "case_input")
    removed = [key for key in REMOVED_V1_KEYS if key in case]
    if removed:
        raise ValueError(
            f"case input carries removed v1 keys {removed}: build a {CASE_INPUT_SCHEMA!r} case "
            "(there is no fixture clock, single constraint snapshot or intrabar map in v2)"
        )
    if case.get("case_input_schema") != CASE_INPUT_SCHEMA:
        found = case.get("case_input_schema")
        raise ValueError(f"case_input_schema must be {CASE_INPUT_SCHEMA!r}, got {found!r}")
    unknown = sorted(set(case) - set(REQUIRED_KEYS) - set(OPTIONAL_KEYS))
    if unknown:
        raise ValueError(f"case input has unknown keys {unknown}")
    absent = [key for key in REQUIRED_KEYS if key not in case]
    if absent:
        raise ValueError(f"case input is missing keys {absent}")
    _reject_floats(case, "case_input")

    symbols = _symbols(case["symbols"])
    account = _parse_account(case["account_state"])
    start_utc, end_utc = _parse_window(case["data_window"])

    minute_source: MinuteSource | None = None
    if "trade_bars_1m" in case or "mark_bars_1m" in case:
        trade = _parse_minutes(
            case.get("trade_bars_1m", []), name="trade_bars_1m", kind="trade", symbols=symbols
        )
        mark = _parse_minutes(
            case.get("mark_bars_1m", []), name="mark_bars_1m", kind="mark", symbols=symbols
        )
        minute_source = ListMinuteSource(trade=trade, mark=mark)

    dataset_id = case.get("dataset_id")
    if dataset_id is not None and (
        not isinstance(dataset_id, str) or not _HEX64_PATTERN.fullmatch(dataset_id)
    ):
        raise ValueError(
            f"dataset_id must be a 64-character lowercase hex string, got {dataset_id!r}"
        )

    scripted = (
        _parse_scripted(case["scripted_plans"], symbols, account)
        if "scripted_plans" in case
        else None
    )
    return ParsedCase(
        strategy_id=_require_str(case["strategy_id"], "strategy_id"),
        strategy_version=_require_str(case["strategy_version"], "strategy_version"),
        parameter_set_id=_require_str(case["parameter_set_id"], "parameter_set_id"),
        symbols=symbols,
        strategy_bars=_parse_bars(
            case["strategy_bars"], name="strategy_bars", interval=STRATEGY_INTERVAL, symbols=symbols
        ),
        context_bars=_parse_bars(
            case["context_bars"], name="context_bars", interval=CONTEXT_INTERVAL, symbols=symbols
        ),
        minute_source=minute_source,
        funding_rows=_parse_funding(case["funding"], symbols),
        constraints=_parse_constraints(case["constraint_history"], symbols),
        account_state=account,
        cost_model=_parse_cost_model(case["cost_model"]),
        data_start_utc=start_utc,
        data_end_utc=end_utc,
        allowed_gaps=_parse_gaps(case["allowed_gaps"], symbols),
        dataset_id=dataset_id,
        scripted_plans=scripted,
    )


__all__ = [
    "CASE_INPUT_SCHEMA",
    "CONTEXT_INTERVAL",
    "FUNDING_SERIES",
    "OPTIONAL_KEYS",
    "REMOVED_V1_KEYS",
    "REQUIRED_KEYS",
    "STRATEGY_INTERVAL",
    "AllowedGap",
    "ParsedCase",
    "ScriptedPlan",
    "parse_case_input",
]
