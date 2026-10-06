"""Counts-only geometry census over local closed 1H and 4H bars (Phase 15, plan 15-07).

Run from the repository root::

    .venv/Scripts/python scripts/geometry_census.py --strategy-id trend-pullback \\
        --parameter-set-id baseline-v5 --symbols BTCUSDT,ETHUSDT,SOLUSDT --days 30 \\
        --end-day 2026-10-01

For every closed 1H bar of the window and every symbol the census calls the same public
functions the backtest engine calls, on the same window sizes (`STRATEGY_WINDOW_BARS`
1H bars, `CONTEXT_WINDOW_BARS` 4H bars): `evaluate`, then `plan`, then `size_and_quantize`.
It counts, per symbol: setups, strategy NO_TRADE reasons, planner NO_TRADE reasons, the two
Phase 12 pre-quantization guard verdicts (STOP_TOO_TIGHT, COST_TO_RISK_EXCEEDED, pass) and
the geometry-invariant violations of every produced plan (D-11, F8).

COUNTS ONLY (D-17). This script never computes or prints PnL, fills, exits, win rates or any
trade outcome, and it is never to be run at alternative parameter values to compare them: a
value chosen after looking at a count is a value chosen by outcome. The counts are
information for the user's parameter decision, nothing else.

The guard stage uses a NEUTRAL constraint snapshot (tick, step, minimum quantity and minimum
notional all 0.00000001), so quantization never rejects and only the two pre-quantization
guards can fire. Real exchange constraints are never invented here; a plan that the neutral
snapshot still rejects for another reason is counted under `guard_other`, not as a pass.

The invariant checker (`geometry_violations`) compares stored plan fields with literal
comparisons. It does not import the planner's validator, so it can catch a defect in it (F8).

Exit codes:

    0  the census finished and found zero invariant violations
    1  the census finished and at least one produced plan violated an invariant
    2  usage error: bad or missing argument, or an unusable parameter set
    3  the store or the run failed (exception type name only)

The window comes only from `--end-day` and `--days`, never from the wall clock. `--warmup-days`
extra days before the window are read so the first evaluated bar sees full strategy and context
windows; bars of the warm-up are not evaluated. `--registry-root` points the registry at a
scratch directory (draft parameter sets live there, never under `params/`). Reads no network.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.backtest.costs import (  # noqa: E402
    build_cost_model,
    cost_rates_from_model,
    cost_slice,
    guard_rates_from_params,
)
from src.backtest.semantics import CONTEXT_WINDOW_BARS, STRATEGY_WINDOW_BARS  # noqa: E402
from src.core.planner import plan as build_trade_plan  # noqa: E402
from src.core.strategy import evaluate  # noqa: E402
from src.core.types import AccountState, Candle, MarketSnapshot  # noqa: E402
from src.data.case_input import build_case_input_data  # noqa: E402
from src.data.minute_source import SYMBOL_RE  # noqa: E402
from src.domain import registry  # noqa: E402
from src.domain.enums import RejectionReason  # noqa: E402
from src.domain.registry import ParameterSet, load_parameter_set  # noqa: E402
from src.domain.trade_plan import TradePlan  # noqa: E402
from src.risk import ConstraintSnapshot  # noqa: E402
from src.risk.gating import size_and_quantize  # noqa: E402

EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_USAGE = 2
EXIT_FAILURE = 3

_SOURCE_TIMEFRAME = "1h"
# Account risk rate used when a set carries no `risk_rate` key (the v6 sets omit it: no src/
# module reads it, the account risk rate is the sizing source, WR-03). The value is the
# documented per-trade rate of docs/trading/RISK_MANAGEMENT.md section 1, not a tuned input.
ACCOUNT_RISK_RATE = Decimal("0.005")
_NEUTRAL = Decimal("0.00000001")
_GUARD_REASONS = frozenset(
    {
        RejectionReason.STOP_TOO_TIGHT.value,
        RejectionReason.COST_TO_RISK_EXCEEDED.value,
    }
)
_DIRECTION_KEYS = ("setups", "plans", "guard_pass", "guard_reject", "invariant_violations")


class _UsageError(Exception):
    """A bad argument or an unusable parameter set (exit 2)."""


class _ArgumentParser(argparse.ArgumentParser):
    """argparse that raises instead of exiting, so `main` returns the exit code."""

    def error(self, message: str) -> Any:
        raise _UsageError(message)


# --------------------------------------------------------------------------- #
# Counters
# --------------------------------------------------------------------------- #


@dataclasses.dataclass
class CensusCounts:
    """Counters of one census run. Counts only: no money, no outcome (D-17)."""

    bars_evaluated: int = 0
    setups: int = 0
    plans: int = 0
    guard_pass: int = 0
    invariant_violations: int = 0
    strategy_no_trade: dict[str, int] = dataclasses.field(default_factory=dict)
    planner_no_trade: dict[str, int] = dataclasses.field(default_factory=dict)
    guard_reject: dict[str, int] = dataclasses.field(default_factory=dict)
    guard_other: dict[str, int] = dataclasses.field(default_factory=dict)
    violation_kinds: dict[str, int] = dataclasses.field(default_factory=dict)
    by_direction: dict[str, dict[str, int]] = dataclasses.field(default_factory=dict)

    def _direction(self, direction: str) -> dict[str, int]:
        return self.by_direction.setdefault(direction, dict.fromkeys(_DIRECTION_KEYS, 0))

    def to_dict(self) -> dict[str, Any]:
        """A plain, JSON-ready copy (dict keys are sorted by the caller's dumps)."""
        return {
            "bars_evaluated": self.bars_evaluated,
            "setups": self.setups,
            "plans": self.plans,
            "guard_pass": self.guard_pass,
            "invariant_violations": self.invariant_violations,
            "strategy_no_trade": dict(self.strategy_no_trade),
            "planner_no_trade": dict(self.planner_no_trade),
            "guard_reject": dict(self.guard_reject),
            "guard_other": dict(self.guard_other),
            "violation_kinds": dict(self.violation_kinds),
            "by_direction": {k: dict(v) for k, v in self.by_direction.items()},
        }

    def merge(self, other: CensusCounts) -> None:
        """Add every counter of `other` into this one."""
        self.bars_evaluated += other.bars_evaluated
        self.setups += other.setups
        self.plans += other.plans
        self.guard_pass += other.guard_pass
        self.invariant_violations += other.invariant_violations
        for mine, theirs in (
            (self.strategy_no_trade, other.strategy_no_trade),
            (self.planner_no_trade, other.planner_no_trade),
            (self.guard_reject, other.guard_reject),
            (self.guard_other, other.guard_other),
            (self.violation_kinds, other.violation_kinds),
        ):
            for key, value in theirs.items():
                mine[key] = mine.get(key, 0) + value
        for direction, row in other.by_direction.items():
            target = self._direction(direction)
            for key, value in row.items():
                target[key] = target.get(key, 0) + value


def _bump(table: dict[str, int], key: str) -> None:
    table[key] = table.get(key, 0) + 1


def exit_code_for(counts: CensusCounts) -> int:
    """0 when no produced plan violated an invariant, else 1."""
    return EXIT_VIOLATION if counts.invariant_violations > 0 else EXIT_OK


# --------------------------------------------------------------------------- #
# Independent invariant checker (F8)
# --------------------------------------------------------------------------- #


def geometry_violations(trade_plan: TradePlan, direction: str) -> list[str]:
    """Names of the geometry invariants a produced plan breaks; `[]` for a valid plan.

    LONG: `stop_loss_price < entry_min_price <= entry_max_price` and TP1 above the zone
    midpoint. SHORT is the mirror. Literal comparisons on the stored fields only: this does
    not call or import the planner's validator, so a defect in that validator cannot make
    this check agree with it (F8).
    """
    if direction not in ("LONG", "SHORT"):
        raise ValueError(f"direction must be LONG or SHORT, got {direction!r}")
    lowest = trade_plan.entry_min_price
    highest = trade_plan.entry_max_price
    stop = trade_plan.stop_loss_price
    found: list[str] = []
    if lowest > highest:
        found.append("zone_inverted")
    entry_ref = (lowest + highest) / 2
    if direction == "LONG":
        if not stop < lowest:
            found.append("stop_inside_zone")
    elif not stop > highest:
        found.append("stop_inside_zone")
    try:
        loaded = json.loads(trade_plan.take_profit_json)
        tp1 = Decimal(str(loaded["tp1"]))
        if not tp1.is_finite():
            raise ValueError("tp1 is not finite")
    except (ValueError, KeyError, TypeError, InvalidOperation):
        found.append("tp1_unreadable")
        return found
    if direction == "LONG":
        if not tp1 > entry_ref:
            found.append("tp1_loss_side")
    elif not tp1 < entry_ref:
        found.append("tp1_loss_side")
    return found


# --------------------------------------------------------------------------- #
# Census over a list of evaluated bar indices
# --------------------------------------------------------------------------- #


def census_window(
    *,
    setup_bars: Sequence[Candle],
    context_bars: Sequence[Candle],
    indices: Sequence[int],
    parameter_set: ParameterSet,
    equity: Decimal,
) -> CensusCounts:
    """Count the outcomes of the real pipeline at each index of `setup_bars`.

    Mirrors the engine: the setup window is the trailing `STRATEGY_WINDOW_BARS` bars ending
    at the evaluated bar, the context window the trailing `CONTEXT_WINDOW_BARS` 4H bars
    closed at or before that bar's close. Each index runs `evaluate`, then `plan`, then
    `size_and_quantize` on a neutral constraint snapshot, and counts the verdicts. Nothing is
    filled, held or exited.
    """
    params = parameter_set.params
    cost_rates = cost_rates_from_model(build_cost_model(cost_slice(params)))
    min_stop_distance_rate, max_cost_to_risk = guard_rates_from_params(params)
    min_utilization = Decimal(str(params["minimum_risk_utilization_after_rounding"]))
    account = AccountState(
        equity=equity, risk_rate=Decimal(str(params.get("risk_rate", ACCOUNT_RISK_RATE)))
    )
    setup_closes = [bar.close_time_utc for bar in setup_bars]
    context_closes = [bar.close_time_utc for bar in context_bars]
    counts = CensusCounts()
    for index in indices:
        close = setup_closes[index]
        high = bisect_right(setup_closes, close)
        setup = list(setup_bars[max(0, high - STRATEGY_WINDOW_BARS) : high])
        context_high = bisect_right(context_closes, close)
        context = list(context_bars[max(0, context_high - CONTEXT_WINDOW_BARS) : context_high])
        counts.bars_evaluated += 1
        snapshot = MarketSnapshot(
            symbol=setup[-1].symbol,
            setup_candles=setup,
            context_candles=context,
            source_timeframe=_SOURCE_TIMEFRAME,
        )
        result = evaluate(
            snapshot=snapshot,
            account_state=account,
            strategy_version=parameter_set.strategy_version,
            parameter_set=parameter_set,
        )
        signal = result.signal
        if result.is_no_trade or signal is None:
            _bump(counts.strategy_no_trade, result.reason_code)
            continue
        direction = signal.direction
        counts.setups += 1
        counts._direction(direction)["setups"] += 1
        planned = build_trade_plan(
            signal=signal,
            setup_candles=setup,
            parameter_set=parameter_set,
            account_state=account,
            created_at_utc=close,
        )
        if planned.is_no_trade or planned.trade_plan is None:
            _bump(counts.planner_no_trade, planned.reason_code)
            continue
        trade_plan = planned.trade_plan
        counts.plans += 1
        counts._direction(direction)["plans"] += 1
        found = geometry_violations(trade_plan, direction)
        if found:
            counts.invariant_violations += 1
            counts._direction(direction)["invariant_violations"] += 1
            for kind in found:
                _bump(counts.violation_kinds, kind)
        sized = size_and_quantize(
            trade_plan=trade_plan,
            candidate_position_side=direction,
            account_state=account,
            constraint_snapshot=ConstraintSnapshot(
                symbol=setup[-1].symbol,
                price_tick_size=_NEUTRAL,
                quantity_step_size=_NEUTRAL,
                min_quantity=_NEUTRAL,
                min_notional=_NEUTRAL,
                metadata_observed_at_utc=close,
            ),
            cost_rates=cost_rates,
            min_stop_distance_rate=min_stop_distance_rate,
            max_cost_to_risk=max_cost_to_risk,
            minimum_risk_utilization_after_rounding=min_utilization,
        )
        if not sized.is_no_trade:
            counts.guard_pass += 1
            counts._direction(direction)["guard_pass"] += 1
        elif sized.reason_code in _GUARD_REASONS:
            _bump(counts.guard_reject, sized.reason_code)
            counts._direction(direction)["guard_reject"] += 1
        else:
            _bump(counts.guard_other, sized.reason_code)
    return counts


# --------------------------------------------------------------------------- #
# Store access and CLI
# --------------------------------------------------------------------------- #


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="geometry_census.py",
        description="Counts-only geometry census over local closed 1H and 4H bars.",
    )
    parser.add_argument("--strategy-id", default="trend-pullback")
    parser.add_argument("--parameter-set-id", default="baseline-v5")
    parser.add_argument(
        "--registry-root",
        default=None,
        help="registry directory to read parameter sets from (default: params/)",
    )
    parser.add_argument("--symbols", required=True, help="comma-separated USDT-M symbols")
    parser.add_argument("--days", type=int, default=30, help="whole UTC days evaluated (>= 1)")
    parser.add_argument(
        "--end-day", required=True, help="last UTC day included, YYYY-MM-DD (never the clock)"
    )
    parser.add_argument(
        "--warmup-days",
        type=int,
        default=50,
        help="extra whole days read before the window so evaluated bars see full windows",
    )
    parser.add_argument("--raw-root", default="data/raw", help="published store root")
    parser.add_argument("--stride", type=int, default=1, help="evaluate every Nth closed bar")
    parser.add_argument("--equity", default="1000", help="account equity, a Decimal string")
    return parser


def _symbols(text: str) -> list[str]:
    names = [part.strip() for part in text.split(",") if part.strip()]
    if not names:
        raise _UsageError("--symbols must name at least one symbol")
    for name in names:
        if not SYMBOL_RE.fullmatch(name):
            raise _UsageError("every symbol must match ^[A-Z0-9]+USDT$")
    if len(set(names)) != len(names):
        raise _UsageError("--symbols must not repeat a symbol")
    return sorted(names)


def _equity(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise _UsageError("--equity is not a decimal number") from None
    if not value.is_finite() or value <= 0:
        raise _UsageError("--equity must be a positive finite decimal")
    return value


def _window(end_day: str, days: int) -> tuple[datetime, datetime]:
    """`(start_utc, end_utc)` for the `days` whole UTC days ending on `end_day`."""
    try:
        last = date.fromisoformat(end_day)
    except ValueError:
        raise _UsageError("--end-day must be a YYYY-MM-DD date") from None
    end_utc = datetime(last.year, last.month, last.day, tzinfo=UTC) + timedelta(days=1)
    return end_utc - timedelta(days=days), end_utc


def _candle(row: Mapping[str, Any]) -> Candle:
    return Candle(
        symbol=str(row["symbol"]),
        interval=str(row["interval"]),
        open_time_utc=datetime.fromisoformat(str(row["open_time_utc"])),
        close_time_utc=datetime.fromisoformat(str(row["close_time_utc"])),
        open=Decimal(str(row["open"])),
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
        volume=Decimal(str(row["volume"])),
    )


def _load_bars(
    raw_root: Path, symbol: str, start_utc: datetime, end_utc: datetime
) -> tuple[list[Candle], list[Candle]]:
    """Closed 1H and 4H trade bars of one symbol, sorted by close time."""
    data = build_case_input_data(
        raw_root,
        symbols=[symbol],
        start_utc=start_utc,
        end_utc=end_utc,
        as_of_day_utc=end_utc.date(),
        series=("trade",),
    )
    setup = sorted((_candle(r) for r in data.strategy_bars), key=lambda c: c.close_time_utc)
    context = sorted((_candle(r) for r in data.context_bars), key=lambda c: c.close_time_utc)
    return setup, context


def _evaluated_indices(
    setup: Sequence[Candle], start_utc: datetime, end_utc: datetime, stride: int
) -> list[int]:
    inside = [i for i, bar in enumerate(setup) if start_utc <= bar.close_time_utc <= end_utc]
    return inside[::stride]


def _emit(line: dict[str, Any]) -> None:
    print(json.dumps(line, sort_keys=True), flush=True)


def _execute(args: argparse.Namespace) -> int:
    symbols = _symbols(args.symbols)
    if args.days < 1:
        raise _UsageError("--days must be at least 1")
    if args.warmup_days < 0:
        raise _UsageError("--warmup-days must not be negative")
    if args.stride < 1:
        raise _UsageError("--stride must be at least 1")
    equity = _equity(args.equity)
    start_utc, end_utc = _window(args.end_day, args.days)
    read_start = start_utc - timedelta(days=args.warmup_days)

    try:
        parameter_set = load_parameter_set(args.strategy_id, args.parameter_set_id)
        census_window(
            setup_bars=[],
            context_bars=[],
            indices=[],
            parameter_set=parameter_set,
            equity=equity,
        )
    except Exception as exc:
        raise _UsageError(f"parameter set unusable ({type(exc).__name__})") from None

    raw_root = Path(args.raw_root)
    total = CensusCounts()
    header = {
        "days": args.days,
        "end_day": args.end_day,
        "equity": str(equity),
        "parameter_set_hash": parameter_set.parameter_set_hash,
        "parameter_set_id": args.parameter_set_id,
        "stride": args.stride,
        "strategy_id": args.strategy_id,
        "warmup_days": args.warmup_days,
    }
    for symbol in symbols:
        setup, context = _load_bars(raw_root, symbol, read_start, end_utc)
        counts = census_window(
            setup_bars=setup,
            context_bars=context,
            indices=_evaluated_indices(setup, start_utc, end_utc, args.stride),
            parameter_set=parameter_set,
            equity=equity,
        )
        _emit({"kind": "symbol", "symbol": symbol, **header, **counts.to_dict()})
        total.merge(counts)
    _emit({"kind": "total", "symbols": symbols, **header, **total.to_dict()})
    return exit_code_for(total)


def _quiet_logs() -> None:
    """Silence structlog decision-lineage events so stdout carries only the JSON lines."""
    import structlog

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))


def main(argv: Sequence[str] | None = None) -> int:
    default_root = registry.REGISTRY_ROOT
    try:
        args = _parser().parse_args(list(argv) if argv is not None else None)
        if args.registry_root is not None:
            registry.REGISTRY_ROOT = Path(args.registry_root)
        _quiet_logs()
        return _execute(args)
    except _UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except SystemExit as exc:  # argparse --help
        return int(exc.code) if isinstance(exc.code, int) else EXIT_OK
    except Exception as exc:
        # Store or run failure: the exception type name only (no path or payload).
        print(f"error: run failed ({type(exc).__name__})", file=sys.stderr)
        return EXIT_FAILURE
    finally:
        registry.REGISTRY_ROOT = default_root
        import structlog

        structlog.reset_defaults()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
