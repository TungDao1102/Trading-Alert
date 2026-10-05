"""Compact case-input v2 builders for the engine tests (Phase 14, plan 14-08).

Every later Phase 14 plan builds its engine, normalizer and golden cases on these
factories so no test spells a v2 case by hand. Every value is a string (never a
float): the v2 parser refuses floats anywhere in a case.

- `make_case`: a v2 case dict from compact arguments (bars per symbol, minute rows,
  funding rows, constraint rows, scripted plans).
- `scripted_plan`, `minute_row`, `flat_minutes`, `funding_row`, `constraint_row`,
  `bar_row`: the row factories `make_case` consumes.
- `fixed_risk_fn`: a stand-in for `evaluate_risk` with a hand-chosen quantity and
  realized risk, so a test controls the sizing instead of re-deriving it.
- `phase6_strategy_rows`: the strategy and context rows of a phase 6 fixture input,
  read key by key so the helper keeps working after the fixtures are regenerated.
- `strategy_run_summary`, `assemble_kwargs`, `make_experiment_record`: the one shared
  factory for typed experiment records (Phase 14, plan 14-15). Every test that needs an
  `ExperimentRecord` or an `assemble` call builds it here; none spells the typed fields
  by hand.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.backtest.semantics import (
    CONTEXT_WINDOW_BARS,
    PLAN_SOURCE_STRATEGY,
    SIMULATOR_SEMANTICS_VERSION,
    STRATEGY_WINDOW_BARS,
    TIE_BREAK,
)
from src.domain.enums import DailyState, QuantizationDecision
from src.risk.types import PortfolioVerdict, SizedResult

SYMBOL = "BTCUSDT"
SIGNAL_CLOSE = datetime(2026, 1, 5, 9, 59, 59, 999000, tzinfo=UTC)
DATA_START = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
DATA_END = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
CONSTRAINT_OBSERVED = datetime(2025, 12, 1, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "phase6"

# The baseline-v5 cost slice (strings), so the registry binding gate passes.
DEFAULT_COST_MODEL: dict[str, str] = {
    "fee_rate_entry": "0.0005",
    "fee_rate_exit": "0.0005",
    "funding_treatment": "ADDITIVE",
    "expected_slippage": "0.0001",
    "slippage_model": "FIXED_BPS",
    "spread_fill_assumptions": "FULL_FILL",
    "partial_fill_fraction": "1.0",
    "exit_slippage_rate": "0.0003",
    "funding_convention": "MARK_NOTIONAL_SIGNED_V1",
}


def D(text: str) -> Decimal:  # noqa: N802 - terse fixture helper
    """Build a Decimal from a string (never from a float)."""
    if not isinstance(text, str):
        raise TypeError(f"D() takes a str, got {type(text).__name__}")
    return Decimal(text)


def at(hour: int, minute: int = 0, *, day: int = 5) -> datetime:
    """A whole-minute UTC instant on 2026-01-<day>."""
    return datetime(2026, 1, day, hour, minute, tzinfo=UTC)


def minute_close(open_time: datetime) -> datetime:
    """Close time of a 1m minute built by `minute_row` (open + 59.999 s)."""
    return open_time + timedelta(seconds=59, milliseconds=999)


def minute_row(
    symbol: str,
    open_time: datetime,
    open_: str,
    high: str,
    low: str,
    close: str,
    *,
    kind: str,
) -> dict[str, str]:
    """One 1m row of a case (`kind` is "trade" with volume or "mark" without)."""
    if kind not in ("trade", "mark"):
        raise ValueError(f"kind must be 'trade' or 'mark', got {kind!r}")
    row = {
        "symbol": symbol,
        "interval": "1m",
        "open_time_utc": open_time.isoformat(),
        "close_time_utc": minute_close(open_time).isoformat(),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
    }
    if kind == "trade":
        row["volume"] = "1"
    return row


def flat_minutes(
    symbol: str,
    start: datetime,
    count: int,
    price: str,
    *,
    kind: str,
    half_range: str = "0.05",
) -> list[dict[str, str]]:
    """`count` consecutive flat minutes from `start`: open = close = `price`, +- `half_range`."""
    centre = D(price)
    half = D(half_range)
    return [
        minute_row(
            symbol,
            start + MINUTE * index,
            str(centre),
            str(centre + half),
            str(centre - half),
            str(centre),
            kind=kind,
        )
        for index in range(count)
    ]


def bar_row(
    symbol: str,
    open_time: datetime,
    open_: str,
    high: str,
    low: str,
    close: str,
    *,
    interval: str = "1h",
) -> dict[str, str]:
    """One strategy (1h) or context (4h) bar row; the close is 1 ms before the next open."""
    span = HOUR if interval == "1h" else HOUR * 4
    return {
        "symbol": symbol,
        "interval": interval,
        "open_time_utc": open_time.isoformat(),
        "close_time_utc": (open_time + span - timedelta(milliseconds=1)).isoformat(),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": "1",
    }


def scripted_plan(
    symbol: str,
    bar_close: datetime,
    signal_id: str,
    direction: str = "LONG",
    *,
    entry_min: str = "99.00",
    entry_max: str = "101.00",
    stop: str = "98.00",
    tp1: str = "104.00",
    tp2: str = "108.00",
    expiry_hours: int = 4,
    invalidation_level: str | None = None,
    regime: str | None = None,
) -> dict[str, Any]:
    """One scripted plan row, scheduled at `bar_close` (a strategy-bar close of `symbol`).

    `regime` (optional) is the label the engine copies onto the plan's records.
    """
    row: dict[str, Any] = {
        "symbol": symbol,
        "bar_close_utc": bar_close.isoformat(),
        "signal_id": signal_id,
        "direction": direction,
        "entry_min_price": entry_min,
        "entry_max_price": entry_max,
        "stop_loss_price": stop,
        "tp1": tp1,
        "tp2": tp2,
        "expiry_hours": expiry_hours,
    }
    if invalidation_level is not None:
        row["invalidation_level"] = invalidation_level
    if regime is not None:
        row["regime"] = regime
    return row


def funding_row(
    symbol: str, when: datetime, rate: str = "0", mark: str | None = "100"
) -> dict[str, Any]:
    """One funding-history row (`mark` None means the exchange row had no mark price)."""
    return {
        "symbol": symbol,
        "funding_time_utc": when.isoformat(),
        "funding_rate": rate,
        "mark_price": mark,
    }


def default_funding(symbols: Sequence[str]) -> list[dict[str, Any]]:
    """Zero-rate funding at 00:00, 08:00 and 16:00 UTC from 2026-01-04 16:00 to 2026-01-06 00:00."""
    instants = [
        datetime(2026, 1, 4, 16, 0, tzinfo=UTC),
        datetime(2026, 1, 5, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
        datetime(2026, 1, 5, 16, 0, tzinfo=UTC),
        datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
    ]
    return [funding_row(symbol, when) for symbol in symbols for when in instants]


def constraint_row(
    symbol: str,
    observed: datetime = CONSTRAINT_OBSERVED,
    *,
    tick: str = "0.10",
    step: str = "0.001",
    min_qty: str = "0.001",
    min_notional: str = "5",
) -> dict[str, str]:
    """One point-in-time exchange-constraint row."""
    return {
        "symbol": symbol,
        "metadata_observed_at_utc": observed.isoformat(),
        "price_tick_size": tick,
        "quantity_step_size": step,
        "min_quantity": min_qty,
        "min_notional": min_notional,
    }


def make_case(
    *,
    symbols: Sequence[str] = (SYMBOL,),
    scripted: Sequence[dict[str, Any]] | None = None,
    strategy_bars: Sequence[dict[str, str]] = (),
    context_bars: Sequence[dict[str, str]] = (),
    trade_minutes: Sequence[dict[str, str]] = (),
    mark_minutes: Sequence[dict[str, str]] = (),
    funding: Sequence[dict[str, Any]] | None = None,
    constraints: Sequence[dict[str, str]] | None = None,
    equity: str = "10000",
    risk_rate: str = "0.005",
    cost_overrides: dict[str, str] | None = None,
    data_start: datetime = DATA_START,
    data_end: datetime = DATA_END,
    allowed_gaps: Sequence[dict[str, Any]] = (),
    dataset_id: str | None = None,
    strategy_id: str = "trend-pullback",
    strategy_version: str = "v4.0.0",
    parameter_set_id: str = "baseline-v5",
) -> dict[str, Any]:
    """Build a case-input v2 dict (every number a string).

    `scripted=None` leaves the key out (the strategy front-end runs); a list, even an
    empty one, switches the engine to the scripted front-end. `funding=None` and
    `constraints=None` take the defaults (zero-rate funding around the day, one
    constraint row per symbol observed 2025-12-01).
    """
    cost_model = dict(DEFAULT_COST_MODEL)
    if cost_overrides:
        cost_model.update(cost_overrides)
    case: dict[str, Any] = {
        "case_input_schema": "backtest-case/2",
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "parameter_set_id": parameter_set_id,
        "symbols": list(symbols),
        "strategy_bars": list(strategy_bars),
        "context_bars": list(context_bars),
        "trade_bars_1m": list(trade_minutes),
        "mark_bars_1m": list(mark_minutes),
        "funding": list(default_funding(symbols) if funding is None else funding),
        "constraint_history": list(
            [constraint_row(s) for s in symbols] if constraints is None else constraints
        ),
        "account_state": {"equity": equity, "risk_rate": risk_rate},
        "cost_model": cost_model,
        "data_window": {"start_utc": data_start.isoformat(), "end_utc": data_end.isoformat()},
        "allowed_gaps": list(allowed_gaps),
    }
    if dataset_id is not None:
        case["dataset_id"] = dataset_id
    if scripted is not None:
        case["scripted_plans"] = list(scripted)
    return case


def fixed_risk_fn(
    quantity: str,
    realized_risk: str,
    *,
    calls: list[dict[str, Any]] | None = None,
) -> Callable[..., PortfolioVerdict]:
    """A stand-in for `evaluate_risk` that always passes with a hand-chosen size.

    Every keyword the engine passes is appended to `calls` (when given), so a test can
    read the ledger projections the engine handed over. The hand size replaces the
    sizing math only; the engine's own gates (TP1 sizeability, partial fills, one entity
    per symbol) still run on top of it.
    """

    def risk_fn(**kwargs: Any) -> PortfolioVerdict:
        if calls is not None:
            calls.append(kwargs)
        sized = SizedResult(
            is_no_trade=False,
            quantity=D(quantity),
            quantity_before_rounding=D(quantity),
            quantity_after_rounding=D(quantity),
            quantization_decision=QuantizationDecision.ACCEPTED.value,
            realized_risk=D(realized_risk),
        )
        return PortfolioVerdict(
            is_no_trade=False, sized=sized, reason_code="OK", daily_state=DailyState.NORMAL
        )

    return risk_fn


def phase6_strategy_rows(fixture: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return `(strategy_bars, context_bars)` rows of a phase 6 fixture `input.json`.

    Only these two keys are read, so the helper survives plan 14-12 regenerating the file.
    """
    payload = json.loads((FIXTURE_ROOT / fixture / "input.json").read_text(encoding="utf-8"))
    return list(payload["strategy_bars"]), list(payload["context_bars"])


# --------------------------------------------------------------------------- #
# Typed experiment records (Phase 14, plan 14-15).
# --------------------------------------------------------------------------- #

RECORD_START = datetime(2026, 1, 1, tzinfo=UTC)
RECORD_END = datetime(2026, 2, 1, tzinfo=UTC)
CODE_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def strategy_run_summary(
    *,
    start: datetime = RECORD_START,
    end: datetime = RECORD_END,
    **overrides: Any,
) -> dict[str, Any]:
    """A v2 STRATEGY `run_summary` shaped exactly like the engine output (JSON-native).

    Keyword overrides replace single keys, so a test changes one value at a time.
    """
    summary: dict[str, Any] = {
        "allowed_gaps_used": [],
        "constraints_extrapolated_count": 0,
        "context_timeframe": "4h",
        "context_window_bars": CONTEXT_WINDOW_BARS,
        "data_window": {"start_utc": start.isoformat(), "end_utc": end.isoformat()},
        "dataset_id": None,
        "end_of_data_count": 1,
        "fallback_count": 2,
        "gap_through_stop_count": 0,
        "intrabar_tie_break": TIE_BREAK,
        "no_trade_counts": {"CONFLICT_WITH_OPEN_POSITION": 3, "RR_TOO_LOW": 5},
        "pending_at_data_end_count": 0,
        "plan_source": PLAN_SOURCE_STRATEGY,
        "simulator_semantics_version": SIMULATOR_SEMANTICS_VERSION,
        "strategy_window_bars": STRATEGY_WINDOW_BARS,
        "tie_order_note": "ties resolve in (time, symbol) order",
        "timeframe": "1h",
        "touch_no_fill_total": 0,
    }
    summary.update(overrides)
    return dict(sorted(summary.items()))


def assemble_kwargs(**overrides: Any) -> dict[str, Any]:
    """Keyword arguments for `experiment.assemble` that bind baseline-v5 (every value valid)."""
    from src.backtest.costs import build_cost_model
    from src.backtest.experiment import CodeVersion

    kwargs: dict[str, Any] = {
        "parameter_set_id": "baseline-v5",
        "strategy_id": "trend-pullback",
        "strategy_version": "v4.0.0",
        "data_snapshot_id": "1" * 64,
        "code_version": CodeVersion(commit=CODE_COMMIT, dirty=False),
        "cost_model": build_cost_model(dict(DEFAULT_COST_MODEL)),
        "time_range_start_utc": RECORD_START,
        "time_range_end_utc": RECORD_END,
        "universe": ["BTCUSDT"],
        "run_type": "CANDIDATE",
        "run_summary": strategy_run_summary(),
        "split_role": "DEVELOPMENT",
        "split_start_utc": RECORD_START,
        "split_end_utc": RECORD_END,
        "notes": "",
        "result_summary_json": "{}",
    }
    kwargs.update(overrides)
    if "run_identity" not in overrides:
        kwargs["run_identity"] = run_identity_for(kwargs)
    return kwargs


def run_identity_for(kwargs: dict[str, Any]) -> dict[str, Any]:
    """The engine-output identity keys that match `assemble` kwargs (CR-02 binding)."""
    from src.domain.registry import load_parameter_set

    parameter_set = load_parameter_set(kwargs["strategy_id"], kwargs["parameter_set_id"])
    return {
        "strategy_version": parameter_set.strategy_version,
        "parameter_set_hash": parameter_set.parameter_set_hash,
        "cost_model_hash": kwargs["cost_model"].cost_model_hash,
        "symbols": sorted(kwargs["universe"]),
    }


def make_experiment_record(
    *, cost_overrides: dict[str, str] | None = None, **overrides: Any
) -> Any:
    """A valid typed `ExperimentRecord` (assembled from baseline-v5), with fields replaced.

    `overrides` are field names of the record; they go through `dataclasses.replace`, so an
    invalid value raises `IncompleteExperimentRecord` exactly as a direct construction does.
    `cost_overrides` swaps cost values AND the matching cost hash in one step (the record
    binds the two), for tests that need a second, different cost identity.
    """
    import dataclasses

    from src.backtest.costs import build_cost_model
    from src.backtest.experiment import assemble, cost_value_pairs

    record = assemble(**assemble_kwargs())
    if cost_overrides:
        model = build_cost_model({**DEFAULT_COST_MODEL, **cost_overrides})
        overrides = {
            "cost_values": cost_value_pairs(model),
            "cost_model_hash": model.cost_model_hash,
            **overrides,
        }
    return dataclasses.replace(record, **overrides)
