"""Pure backtest simulator — event-driven bar loop (Phase 6, plan 06-01).

Per D-01/D-02/D-05: the simulator replays closed 1H strategy bars through
strategy.evaluate → planner.plan → evaluate_risk, resolves exits via 1m
intrabar data (SL-first conservative fallback when 1m is missing), and
applies registry-parameterized costs from run #1. The simulator never
re-implements risk math — it delegates to `src/risk/gating.evaluate_risk`
identically.

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 purity precedent.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.core._decimal import _add, _div, _mul, _sub
from src.core.planner import plan
from src.core.strategy import evaluate
from src.core.types import AccountState, Candle, MarketSnapshot
from src.domain.canonical import sha256_hex
from src.domain.registry import ParameterSet, load_parameter_set
from src.domain.trade_plan import TradePlan
from src.risk.gating import evaluate_risk
from src.risk.portfolio import resolve_absolute_thresholds
from src.risk.types import ConstraintSnapshot, OpenPosition

from .costs import CostModel, build_cost_model, modeled_costs_per_unit

# --------------------------------------------------------------------------- #
# Validation helpers — local copies (D-12 fail-closed).
# --------------------------------------------------------------------------- #


def _require_decimal(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")
    return value


def _require_utc_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


def _require_non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field_name} must be a non-empty string")


def _coerce_money(value: object, field_name: str) -> Decimal:
    """Coerce a money/rate JSON field to Decimal, fail-closed (D-12).

    JSON numbers decode as Python float/int; a float (e.g. `1.1`)
    would inject binary noise via `Decimal(1.1000000000000000888…)`,
    so floats are REJECTED, never coerced. Decimal passes through,
    int is exact, str keeps its spelling.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be Decimal/str/int, got bool")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        return Decimal(value)
    raise TypeError(
        f"{field_name} must be Decimal/str/int, got {type(value).__name__}"
    )


def _parse_utc_aware(raw: object, field_name: str) -> datetime:
    """Parse an ISO string into a UTC-aware datetime, fail-closed."""
    if not isinstance(raw, str):
        raise TypeError(f"{field_name} must be ISO str, got {type(raw).__name__}")
    value = datetime.fromisoformat(raw)
    _require_utc_aware(value, field_name)
    return value


# --------------------------------------------------------------------------- #
# IntrabarOutcome — frozen result of 1m intrabar resolution.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class IntrabarOutcome:
    """Result of resolving a strategy bar's exit via 1m intrabar data.

    `fallback_applied=True` means 1m data was missing and the SL-first
    conservative fallback was used (D-01 + Phase-2 D-09 flag-never-fabricate).
    `coverage_note` carries the reason string for the report.
    """

    exit_kind: str  # "SL" | "TP1" | "EOD" (single-exit scope: TP2 runner not modeled)
    price: Decimal
    fallback_applied: bool
    coverage_note: str | None
    exit_time_utc: datetime | None  # deciding 1m candle's close; None on fallback


# --------------------------------------------------------------------------- #
# TradeRecord — frozen per-trade outcome.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TradeRecord:
    """One trade outcome emitted by the simulator.

    `entry_kind` is one of: "ENTRY_FILLED", "PARTIAL_FILL", "TOUCH_NO_FILL",
    "EXPIRED", "INVALIDATION_CANCEL". `exit_kind` is one of: "SL", "TP1",
    "TP2", "EOD", or None if the trade never filled. `outcome_kind` is
    "OK" for filled trades, "REJECT" for risk-rejected plans.
    """

    trade_id: str
    signal_id: str | None
    trade_plan_id: str | None
    strategy_version: str
    parameter_set_hash: str
    symbol: str
    direction: str
    entry_kind: str
    entry_price: Decimal | None
    entry_time_utc: datetime | None
    quantity: Decimal | None
    exit_kind: str | None
    exit_price: Decimal | None
    exit_time_utc: datetime | None
    realized_pnl: Decimal | None
    realized_risk: Decimal | None
    gross_pnl: Decimal | None
    entry_fee: Decimal | None
    exit_fee: Decimal | None
    funding_amount: Decimal | None
    slippage_amount: Decimal | None
    modeled_costs_per_unit: Decimal | None
    coverage_note: str | None
    fallback_applied: bool
    outcome_kind: str  # "OK" | "REJECT"
    reason_code: str  # canonical RejectionReason value or "OK"

    def to_dict(self) -> dict[str, Any]:
        """Project to a canonical-JSON-safe dict for hashing."""
        out: dict[str, Any] = {}
        for k, v in self.__dict__.items():
            if isinstance(v, Decimal):
                out[k] = str(v)
            elif isinstance(v, datetime):
                out[k] = v.isoformat()
            else:
                out[k] = v
        return out


# --------------------------------------------------------------------------- #
# SimulatorResult — frozen envelope.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SimulatorResult:
    """The simulator's output: a list of TradeRecords + metadata."""

    trades: list[TradeRecord]
    strategy_version: str
    parameter_set_hash: str
    cost_model_hash: str
    symbol: str


# --------------------------------------------------------------------------- #
# resolve_intrabar — 1m path with SL-first fallback (D-01).
# --------------------------------------------------------------------------- #


def resolve_intrabar(
    *,
    direction: str,
    stop_loss: Decimal,
    take_profit_1: Decimal,
    intrabar: Sequence[Candle] | None,
) -> IntrabarOutcome:
    """Resolve a strategy bar's exit via 1m intrabar data.

    Per D-01: SL is checked BEFORE TP inside each 1m candle (SL-first
    conservative ordering). When 1m data is missing, the SL-first
    fallback fires with `fallback_applied=True` and
    `coverage_note="1m_intrabar_missing"` — never synthesized prices.

    The 1m sequence is walked in order; the first 1m candle that
    touches SL or TP1 determines the exit. If neither is touched, the
    exit is "EOD" at the last 1m candle's close.

    NOTE (single-exit scope): the planner emits a TP1/TP2 ladder, but
    this simulator models one exit per fill. The first profit target
    (TP1) is the realized exit; the TP2 runner leg is NOT modeled —
    exits at TP1 are conservative (profit taken at the nearer target).
    `exit_kind` is therefore one of "SL" | "TP1" | "EOD".
    """
    if direction not in {"LONG", "SHORT"}:
        raise ValueError(f"direction must be LONG or SHORT, got {direction!r}")
    if intrabar is None or len(intrabar) == 0:
        # Phase-2 D-09 flag-never-fabricate: conservative fallback,
        # log the flag on the trade record, never silent. An empty 1m
        # payload (valid JSON, zero candles) is "no coverage" exactly
        # like a missing payload — SL-first fallback, never IndexError.
        return IntrabarOutcome(
            exit_kind="SL",
            price=stop_loss,
            fallback_applied=True,
            coverage_note="1m_intrabar_missing",
            exit_time_utc=None,
        )
    for minute in intrabar:
        if direction == "LONG":
            if minute.low <= stop_loss:
                return IntrabarOutcome(
                    exit_kind="SL",
                    price=stop_loss,
                    fallback_applied=False,
                    coverage_note=None,
                    exit_time_utc=minute.close_time_utc,
                )
            if minute.high >= take_profit_1:
                return IntrabarOutcome(
                    exit_kind="TP1",
                    price=take_profit_1,
                    fallback_applied=False,
                    coverage_note=None,
                    exit_time_utc=minute.close_time_utc,
                )
        else:  # SHORT
            if minute.high >= stop_loss:
                return IntrabarOutcome(
                    exit_kind="SL",
                    price=stop_loss,
                    fallback_applied=False,
                    coverage_note=None,
                    exit_time_utc=minute.close_time_utc,
                )
            if minute.low <= take_profit_1:
                return IntrabarOutcome(
                    exit_kind="TP1",
                    price=take_profit_1,
                    fallback_applied=False,
                    coverage_note=None,
                    exit_time_utc=minute.close_time_utc,
                )
    # Neither SL nor TP touched in any 1m candle → EOD at last close.
    return IntrabarOutcome(
        exit_kind="EOD",
        price=intrabar[-1].close,
        fallback_applied=False,
        coverage_note=None,
        exit_time_utc=intrabar[-1].close_time_utc,
    )


# --------------------------------------------------------------------------- #
# Input parsing — build domain objects from the fixture dict.
# --------------------------------------------------------------------------- #


def _parse_candle(row: dict[str, Any]) -> Candle:
    """Build a Candle from a JSON-decoded dict."""
    _require_non_empty(str(row["symbol"]), "symbol")
    open_time_utc = _parse_utc_aware(row["open_time_utc"], "open_time_utc")
    close_time_utc = _parse_utc_aware(row["close_time_utc"], "close_time_utc")
    return Candle(
        symbol=row["symbol"],
        interval=row["interval"],
        open_time_utc=open_time_utc,
        close_time_utc=close_time_utc,
        open=_coerce_money(row["open"], "open"),
        high=_coerce_money(row["high"], "high"),
        low=_coerce_money(row["low"], "low"),
        close=_coerce_money(row["close"], "close"),
        volume=_coerce_money(row["volume"], "volume"),
    )


def _parse_account_state(d: dict[str, Any]) -> AccountState:
    return AccountState(
        equity=_coerce_money(d["equity"], "equity"),
        risk_rate=_coerce_money(d["risk_rate"], "risk_rate"),
    )


def _parse_constraint_snapshot(d: dict[str, Any]) -> ConstraintSnapshot:
    return ConstraintSnapshot(
        symbol=d["symbol"],
        price_tick_size=_coerce_money(d["price_tick_size"], "price_tick_size"),
        quantity_step_size=_coerce_money(d["quantity_step_size"], "quantity_step_size"),
        min_quantity=_coerce_money(d["min_quantity"], "min_quantity"),
        min_notional=_coerce_money(d["min_notional"], "min_notional"),
        metadata_observed_at_utc=_parse_utc_aware(
            d["metadata_observed_at_utc"], "metadata_observed_at_utc"
        ),
    )


def _parse_open_positions(rows: list[dict[str, Any]]) -> list[OpenPosition]:
    return [
        OpenPosition(
            symbol=r["symbol"],
            position_side=r["position_side"],
            open_risk=_coerce_money(r["open_risk"], "open_risk"),
            daily_pnl_contribution=_coerce_money(
                r.get("daily_pnl_contribution", "0"), "daily_pnl_contribution"
            ),
        )
        for r in rows
    ]


def _parse_intrabar_map(d: dict[str, Any]) -> dict[str, list[Candle] | None]:
    """Parse the intrabar_1m_map: keys are 'SYMBOL|ISO_CLOSE_TIME'."""
    out: dict[str, list[Candle] | None] = {}
    for key, value in d.items():
        if value is None:
            out[key] = None
        else:
            out[key] = [_parse_candle(row) for row in value]
    return out


def _parse_tp1(trade_plan: TradePlan) -> Decimal:
    """Extract TP1 price from the trade plan's take_profit_json."""
    tp_dict = json.loads(trade_plan.take_profit_json)
    return Decimal(tp_dict["tp1"])


# --------------------------------------------------------------------------- #
# Entry state machine — LIMIT touch/partial/expiry/invalidation.
# --------------------------------------------------------------------------- #


def _resolve_entry(
    *,
    trade_plan: TradePlan,
    bar: Candle,
    quantity: Decimal,
    cost_model: CostModel,
    now_utc: datetime,
    direction: str,
) -> TradeRecord:
    """Resolve the entry state machine for one bar.

    Returns a TradeRecord with entry_kind set. If the entry fills, the
    record also carries entry_price, entry_time_utc, and quantity.
    """
    # Check expiry first (no retroactive fill after expiry).
    if now_utc >= trade_plan.expiry_utc:
        return _make_record(
            trade_plan=trade_plan,
            entry_kind="EXPIRED",
            entry_price=None,
            entry_time_utc=None,
            quantity=None,
            exit_kind=None,
            exit_price=None,
            exit_time_utc=None,
            realized_pnl=None,
            realized_risk=None,
            gross_pnl=None,
            entry_fee=None,
            exit_fee=None,
            funding_amount=None,
            slippage_amount=None,
            modeled_costs_per_unit=None,
            coverage_note=None,
            fallback_applied=False,
            outcome_kind="OK",
            reason_code="OK",
            symbol=bar.symbol,
            bar_close_time_utc=bar.close_time_utc,
            direction=direction,
        )

    if direction == "LONG":
        if bar.close < bar.open:
            return _make_record(
                trade_plan=trade_plan,
                entry_kind="INVALIDATION_CANCEL",
                entry_price=None,
                entry_time_utc=None,
                quantity=None,
                exit_kind=None,
                exit_price=None,
                exit_time_utc=None,
                realized_pnl=None,
                realized_risk=None,
                gross_pnl=None,
                entry_fee=None,
                exit_fee=None,
                funding_amount=None,
                slippage_amount=None,
                modeled_costs_per_unit=None,
                coverage_note=None,
                fallback_applied=False,
                outcome_kind="OK",
                reason_code="OK",
                symbol=bar.symbol,
                bar_close_time_utc=bar.close_time_utc,
                direction=direction,
            )
    else:  # SHORT
        if bar.close > bar.open:
            return _make_record(
                trade_plan=trade_plan,
                entry_kind="INVALIDATION_CANCEL",
                entry_price=None,
                entry_time_utc=None,
                quantity=None,
                exit_kind=None,
                exit_price=None,
                exit_time_utc=None,
                realized_pnl=None,
                realized_risk=None,
                gross_pnl=None,
                entry_fee=None,
                exit_fee=None,
                funding_amount=None,
                slippage_amount=None,
                modeled_costs_per_unit=None,
                coverage_note=None,
                fallback_applied=False,
                outcome_kind="OK",
                reason_code="OK",
                symbol=bar.symbol,
                bar_close_time_utc=bar.close_time_utc,
                direction=direction,
            )

    # Check zone touch: bar range must bracket the entry zone.
    zone_touched = bar.high >= trade_plan.entry_min_price and bar.low <= trade_plan.entry_max_price
    if not zone_touched:
        # Bar didn't touch the zone at all.
        return _make_record(
            trade_plan=trade_plan,
            entry_kind="TOUCH_NO_FILL",
            entry_price=None,
            entry_time_utc=None,
            quantity=None,
            exit_kind=None,
            exit_price=None,
            exit_time_utc=None,
            realized_pnl=None,
            realized_risk=None,
            gross_pnl=None,
            entry_fee=None,
            exit_fee=None,
            funding_amount=None,
            slippage_amount=None,
            modeled_costs_per_unit=None,
            coverage_note=None,
            fallback_applied=False,
            outcome_kind="OK",
            reason_code="OK",
            symbol=bar.symbol,
            bar_close_time_utc=bar.close_time_utc,
            direction=direction,
        )

    # Zone touched — fill at entry_ref (zone mid).
    entry_ref = _div(
        _add(trade_plan.entry_min_price, trade_plan.entry_max_price),
        Decimal("2"),
    )
    # Apply partial_fill_fraction.
    filled_quantity = _mul(quantity, cost_model.partial_fill_fraction)
    if filled_quantity <= Decimal("0"):
        return _make_record(
            trade_plan=trade_plan,
            entry_kind="TOUCH_NO_FILL",
            entry_price=None,
            entry_time_utc=None,
            quantity=None,
            exit_kind=None,
            exit_price=None,
            exit_time_utc=None,
            realized_pnl=None,
            realized_risk=None,
            gross_pnl=None,
            entry_fee=None,
            exit_fee=None,
            funding_amount=None,
            slippage_amount=None,
            modeled_costs_per_unit=None,
            coverage_note=None,
            fallback_applied=False,
            outcome_kind="OK",
            reason_code="OK",
            symbol=bar.symbol,
            bar_close_time_utc=bar.close_time_utc,
            direction=direction,
        )
    entry_kind = (
        "PARTIAL_FILL" if cost_model.partial_fill_fraction < Decimal("1") else "ENTRY_FILLED"
    )
    return _make_record(
        trade_plan=trade_plan,
        entry_kind=entry_kind,
        entry_price=entry_ref,
        entry_time_utc=bar.close_time_utc,
        quantity=filled_quantity,
        exit_kind=None,
        exit_price=None,
        exit_time_utc=None,
        realized_pnl=None,
        realized_risk=None,
        gross_pnl=None,
        entry_fee=None,
        exit_fee=None,
        funding_amount=None,
        slippage_amount=None,
        modeled_costs_per_unit=None,
        coverage_note=None,
        fallback_applied=False,
        outcome_kind="OK",
        reason_code="OK",
        symbol=bar.symbol,
        bar_close_time_utc=bar.close_time_utc,
        direction=direction,
    )


def _make_record(
    *,
    trade_plan: TradePlan,
    symbol: str,
    bar_close_time_utc: datetime,
    entry_kind: str,
    entry_price: Decimal | None,
    entry_time_utc: datetime | None,
    quantity: Decimal | None,
    exit_kind: str | None,
    exit_price: Decimal | None,
    exit_time_utc: datetime | None,
    realized_pnl: Decimal | None,
    realized_risk: Decimal | None,
    gross_pnl: Decimal | None,
    entry_fee: Decimal | None,
    exit_fee: Decimal | None,
    funding_amount: Decimal | None,
    slippage_amount: Decimal | None,
    modeled_costs_per_unit: Decimal | None,
    coverage_note: str | None,
    fallback_applied: bool,
    outcome_kind: str,
    reason_code: str,
    direction: str,
) -> TradeRecord:
    """Build a TradeRecord with a deterministic trade_id.

    The ID binds symbol + bar close time + quantity alongside the
    plan/price/kind fields, so two fills of the same plan at different
    fractions, or the same plan on different bars, never collide.
    `symbol` is an explicit caller parameter (never a placeholder).
    """
    _require_non_empty(symbol, "symbol")
    _require_utc_aware(bar_close_time_utc, "bar_close_time_utc")
    payload = {
        "trade_plan_id": trade_plan.trade_plan_id,
        "symbol": symbol,
        "bar_close_time_utc": bar_close_time_utc,
        "entry_kind": entry_kind,
        "entry_price": entry_price,
        "quantity": quantity,
        "exit_kind": exit_kind,
        "exit_price": exit_price,
        "outcome_kind": outcome_kind,
        "reason_code": reason_code,
    }
    trade_id = sha256_hex(payload)
    return TradeRecord(
        trade_id=trade_id,
        signal_id=trade_plan.signal_id,
        trade_plan_id=trade_plan.trade_plan_id,
        strategy_version=trade_plan.trade_plan_version,
        parameter_set_hash=trade_plan.plan_hash,  # placeholder; overwritten below
        symbol=symbol,
        direction=direction,
        entry_kind=entry_kind,
        entry_price=entry_price,
        entry_time_utc=entry_time_utc,
        quantity=quantity,
        exit_kind=exit_kind,
        exit_price=exit_price,
        exit_time_utc=exit_time_utc,
        realized_pnl=realized_pnl,
        realized_risk=realized_risk,
        gross_pnl=gross_pnl,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        funding_amount=funding_amount,
        slippage_amount=slippage_amount,
        modeled_costs_per_unit=modeled_costs_per_unit,
        coverage_note=coverage_note,
        fallback_applied=fallback_applied,
        outcome_kind=outcome_kind,
        reason_code=reason_code,
    )


# --------------------------------------------------------------------------- #
# Cost application — entry fee + exit fee + slippage on realized PnL.
# --------------------------------------------------------------------------- #


def _apply_costs(
    *,
    trade_record: TradeRecord,
    cost_model: CostModel,
) -> TradeRecord:
    """Apply costs to a filled trade record.

    Returns a new TradeRecord with entry_fee, exit_fee, slippage_amount,
    gross_pnl, and realized_pnl populated. For non-filled trades, the
    cost fields remain None.
    """
    if trade_record.entry_price is None or trade_record.quantity is None:
        return trade_record
    if trade_record.exit_price is None:
        return trade_record

    quantity = trade_record.quantity
    entry_price = trade_record.entry_price
    exit_price = trade_record.exit_price

    # Gross PnL: (exit - entry) * quantity for LONG; (entry - exit) * quantity for SHORT.
    if trade_record.direction == "LONG":
        gross_pnl = _mul(_sub(exit_price, entry_price), quantity)
    else:
        gross_pnl = _mul(_sub(entry_price, exit_price), quantity)

    # Fees: entry_fee = entry_price * quantity * fee_rate_entry
    entry_fee = _mul(_mul(entry_price, quantity), cost_model.fee_rate_entry)
    exit_fee = _mul(_mul(exit_price, quantity), cost_model.fee_rate_exit)
    # Slippage: expected_slippage * quantity (in quote currency).
    slippage = _mul(quantity, cost_model.expected_slippage)
    # Funding: ADDITIVE treatment → 0 for the tracer slice (no funding events).
    funding = Decimal("0")

    realized_pnl = _sub(
        _sub(_sub(gross_pnl, entry_fee), exit_fee),
        _add(slippage, funding),
    )

    # Build a new TradeRecord with cost fields populated.
    return TradeRecord(
        trade_id=trade_record.trade_id,
        signal_id=trade_record.signal_id,
        trade_plan_id=trade_record.trade_plan_id,
        strategy_version=trade_record.strategy_version,
        parameter_set_hash=trade_record.parameter_set_hash,
        symbol=trade_record.symbol,
        direction=trade_record.direction,
        entry_kind=trade_record.entry_kind,
        entry_price=trade_record.entry_price,
        entry_time_utc=trade_record.entry_time_utc,
        quantity=trade_record.quantity,
        exit_kind=trade_record.exit_kind,
        exit_price=trade_record.exit_price,
        exit_time_utc=trade_record.exit_time_utc,
        realized_pnl=realized_pnl,
        realized_risk=trade_record.realized_risk,
        gross_pnl=gross_pnl,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        funding_amount=funding,
        slippage_amount=slippage,
        modeled_costs_per_unit=trade_record.modeled_costs_per_unit,
        coverage_note=trade_record.coverage_note,
        fallback_applied=trade_record.fallback_applied,
        outcome_kind=trade_record.outcome_kind,
        reason_code=trade_record.reason_code,
    )


# --------------------------------------------------------------------------- #
# Main entry point — run the simulator.
# --------------------------------------------------------------------------- #


def run(case_input: dict[str, Any]) -> dict[str, Any]:
    """Run the backtest simulator on a fixture input dict.

    Returns a dict with keys: `trades` (list of TradeRecord dicts),
    `strategy_version`, `parameter_set_hash`, `cost_model_hash`,
    `symbol`. The `trades` list is the canonical output for hashing.
    """
    # Parse inputs.
    strategy_id = case_input["strategy_id"]
    strategy_version = case_input["strategy_version"]
    parameter_set_id = case_input["parameter_set_id"]
    strategy_bars = [_parse_candle(r) for r in case_input["strategy_bars"]]
    context_bars = [_parse_candle(r) for r in case_input["context_bars"]]
    intrabar_map = _parse_intrabar_map(case_input["intrabar_1m_map"])
    account_state = _parse_account_state(case_input["account_state"])
    constraint_snapshot = _parse_constraint_snapshot(case_input["constraint_snapshot"])
    cost_model = build_cost_model(case_input["cost_model"])
    open_positions = _parse_open_positions(case_input["open_positions"])
    daily_loss_quote = _coerce_money(case_input["daily_loss_quote"], "daily_loss_quote")
    now_utc = _parse_utc_aware(case_input["now_utc"], "now_utc")
    ttl = timedelta(seconds=int(case_input["ttl_seconds"]))

    # WR: the simulator's wall-clock for the expiry gate is the fixture's
    # now_utc (when the backtest is "running"), NOT the trigger bar's
    # close_time_utc. The signal's expiry_utc is absolute (source close
    # + signal_expiry_hours); a backtest running at now_utc >= expiry_utc
    # means the limit window has already closed without a fill.
    _entry_now_utc = now_utc

    # Load the parameter set from the registry.
    parameter_set = load_parameter_set(strategy_id, parameter_set_id)
    # CR-10: the fixture's strategy_version must match the registry's —
    # otherwise the six-field identity would attest to a combination
    # that was never versioned together. Fail closed on divergence.
    if parameter_set.strategy_version != strategy_version:
        raise ValueError(
            f"fixture strategy_version={strategy_version!r} != "
            f"registry strategy_version={parameter_set.strategy_version!r} "
            f"for {strategy_id}/{parameter_set_id}"
        )

    # Resolve absolute thresholds for the portfolio gate.
    absolute_thresholds = resolve_absolute_thresholds(
        parameter_set=parameter_set.params,
        equity=account_state.equity,
    )

    # Sort strategy bars by (close_time_utc, symbol) for deterministic iteration.
    sorted_bars = sorted(strategy_bars, key=lambda b: (b.close_time_utc, b.symbol))
    # Sort once up front so every closed-context slice is time-ordered too.
    sorted_context = sorted(context_bars, key=lambda c: (c.close_time_utc, c.symbol))

    trades: list[TradeRecord] = []

    for idx, bar in enumerate(sorted_bars):
        # Build MarketSnapshot with closed candles only (D-02). Slice by
        # index into the SORTED lists so out-of-order fixture input still
        # yields time-ordered, prefix-invariant snapshots.
        closed_setup = sorted_bars[: idx + 1]
        closed_context = [c for c in sorted_context if c.close_time_utc <= bar.close_time_utc]
        snapshot = MarketSnapshot(
            symbol=bar.symbol,
            setup_candles=closed_setup,
            context_candles=closed_context,
            source_timeframe="1h",
        )

        # Strategy gate.
        setup_result = evaluate(
            snapshot=snapshot,
            account_state=account_state,
            strategy_version=strategy_version,
            parameter_set=parameter_set,
        )
        if setup_result.is_no_trade:
            # No setup on this bar — skip.
            continue

        signal = setup_result.signal
        assert signal is not None

        # Planner.
        plan_result = plan(
            signal=signal,
            setup_candles=closed_setup,
            parameter_set=parameter_set,
            account_state=account_state,
            created_at_utc=bar.close_time_utc,
        )
        if plan_result.is_no_trade:
            # Planner rejected — emit reject record.
            reject_record = _make_reject_record(
                signal=signal,
                reason_code=plan_result.reason_code,
                parameter_set=parameter_set,
                bar=bar,
            )
            trades.append(reject_record)
            continue

        trade_plan = plan_result.trade_plan
        assert trade_plan is not None

        # Risk pipeline.
        modeled_costs = modeled_costs_per_unit(
            cost_model=cost_model,
            side=signal.direction,
        )
        verdict = evaluate_risk(
            trade_plan=trade_plan,
            candidate_position_side=signal.direction,
            account_state=account_state,
            constraint_snapshot=constraint_snapshot,
            open_positions=open_positions,
            daily_loss_quote=daily_loss_quote,
            now_utc=bar.close_time_utc,
            ttl=ttl,
            modeled_costs_per_unit=modeled_costs,
            minimum_risk_utilization_after_rounding=Decimal(
                str(parameter_set.params["minimum_risk_utilization_after_rounding"])
            ),
            parameter_set=absolute_thresholds,
        )
        if verdict.is_no_trade:
            # Risk rejected — emit reject record.
            reject_record = _make_reject_record(
                signal=signal,
                reason_code=verdict.reason_code,
                parameter_set=parameter_set,
                bar=bar,
                trade_plan=trade_plan,
            )
            trades.append(reject_record)
            continue

        # Risk passed — resolve entry state machine.
        sized = verdict.sized
        assert sized is not None
        assert sized.quantity is not None

        entry_record = _resolve_entry(
            trade_plan=trade_plan,
            bar=bar,
            quantity=sized.quantity,
            cost_model=cost_model,
            now_utc=_entry_now_utc,
            direction=signal.direction,
        )
        # Patch the record with the correct symbol, parameter_set_hash, and modeled_costs.
        entry_record = _patch_record_metadata(
            record=entry_record,
            symbol=bar.symbol,
            parameter_set_hash=parameter_set.parameter_set_hash,
            modeled_costs_per_unit=modeled_costs,
            realized_risk=sized.realized_risk,
        )

        if entry_record.entry_kind in {"ENTRY_FILLED", "PARTIAL_FILL"}:
            # Entry filled — resolve exit via 1m intrabar.
            intrabar_key = f"{bar.symbol}|{bar.close_time_utc.isoformat()}"
            intrabar = intrabar_map.get(intrabar_key)
            tp1 = _parse_tp1(trade_plan)
            outcome = resolve_intrabar(
                direction=signal.direction,
                stop_loss=trade_plan.stop_loss_price,
                take_profit_1=tp1,
                intrabar=intrabar,
            )
            # Build the filled record with exit fields. The exit timestamp
            # is the deciding 1m candle's close (WR-12); only the
            # missing-data fallback (no 1m candle to anchor to) keeps
            # the strategy-bar close.
            filled_record = _make_filled_record(
                entry_record=entry_record,
                exit_kind=outcome.exit_kind,
                exit_price=outcome.price,
                exit_time_utc=(
                    outcome.exit_time_utc
                    if outcome.exit_time_utc is not None
                    else bar.close_time_utc
                ),
                coverage_note=outcome.coverage_note,
                fallback_applied=outcome.fallback_applied,
            )
            # Apply costs.
            filled_record = _apply_costs(
                trade_record=filled_record,
                cost_model=cost_model,
            )
            trades.append(filled_record)
        else:
            # Entry did not fill (TOUCH_NO_FILL, EXPIRED, INVALIDATION_CANCEL).
            trades.append(entry_record)

    # Return the result as a dict for JSON-friendly output.
    return {
        "trades": [t.to_dict() for t in trades],
        "strategy_version": strategy_version,
        "parameter_set_hash": parameter_set.parameter_set_hash,
        "cost_model_hash": cost_model.cost_model_hash,
        "symbol": sorted_bars[0].symbol if sorted_bars else "",
    }


def _make_reject_record(
    *,
    signal: Any,
    reason_code: str,
    parameter_set: ParameterSet,
    bar: Candle,
    trade_plan: TradePlan | None = None,
) -> TradeRecord:
    """Build a REJECT TradeRecord for a risk-rejected plan."""
    payload = {
        "signal_id": signal.signal_id,
        "reason_code": reason_code,
        "bar_close": bar.close_time_utc.isoformat(),
    }
    trade_id = sha256_hex(payload)
    return TradeRecord(
        trade_id=trade_id,
        signal_id=signal.signal_id,
        trade_plan_id=trade_plan.trade_plan_id if trade_plan else None,
        strategy_version=parameter_set.strategy_version,
        parameter_set_hash=parameter_set.parameter_set_hash,
        symbol=bar.symbol,
        direction=signal.direction,
        entry_kind="REJECT",
        entry_price=None,
        entry_time_utc=None,
        quantity=None,
        exit_kind=None,
        exit_price=None,
        exit_time_utc=None,
        realized_pnl=None,
        realized_risk=None,
        gross_pnl=None,
        entry_fee=None,
        exit_fee=None,
        funding_amount=None,
        slippage_amount=None,
        modeled_costs_per_unit=None,
        coverage_note=None,
        fallback_applied=False,
        outcome_kind="REJECT",
        reason_code=reason_code,
    )


def _patch_record_metadata(
    *,
    record: TradeRecord,
    symbol: str,
    parameter_set_hash: str,
    modeled_costs_per_unit: Decimal,
    realized_risk: Decimal,
) -> TradeRecord:
    """Patch a record with the correct symbol, hash, costs, and risk."""
    return TradeRecord(
        trade_id=record.trade_id,
        signal_id=record.signal_id,
        trade_plan_id=record.trade_plan_id,
        strategy_version=record.strategy_version,
        parameter_set_hash=parameter_set_hash,
        symbol=symbol,
        direction=record.direction,
        entry_kind=record.entry_kind,
        entry_price=record.entry_price,
        entry_time_utc=record.entry_time_utc,
        quantity=record.quantity,
        exit_kind=record.exit_kind,
        exit_price=record.exit_price,
        exit_time_utc=record.exit_time_utc,
        realized_pnl=record.realized_pnl,
        realized_risk=realized_risk,
        gross_pnl=record.gross_pnl,
        entry_fee=record.entry_fee,
        exit_fee=record.exit_fee,
        funding_amount=record.funding_amount,
        slippage_amount=record.slippage_amount,
        modeled_costs_per_unit=modeled_costs_per_unit,
        coverage_note=record.coverage_note,
        fallback_applied=record.fallback_applied,
        outcome_kind=record.outcome_kind,
        reason_code=record.reason_code,
    )


def _make_filled_record(
    *,
    entry_record: TradeRecord,
    exit_kind: str,
    exit_price: Decimal,
    exit_time_utc: datetime,
    coverage_note: str | None,
    fallback_applied: bool,
) -> TradeRecord:
    """Build a filled TradeRecord with exit fields populated."""
    return TradeRecord(
        trade_id=entry_record.trade_id,
        signal_id=entry_record.signal_id,
        trade_plan_id=entry_record.trade_plan_id,
        strategy_version=entry_record.strategy_version,
        parameter_set_hash=entry_record.parameter_set_hash,
        symbol=entry_record.symbol,
        direction=entry_record.direction,
        entry_kind=entry_record.entry_kind,
        entry_price=entry_record.entry_price,
        entry_time_utc=entry_record.entry_time_utc,
        quantity=entry_record.quantity,
        exit_kind=exit_kind,
        exit_price=exit_price,
        exit_time_utc=exit_time_utc,
        realized_pnl=entry_record.realized_pnl,
        realized_risk=entry_record.realized_risk,
        gross_pnl=entry_record.gross_pnl,
        entry_fee=entry_record.entry_fee,
        exit_fee=entry_record.exit_fee,
        funding_amount=entry_record.funding_amount,
        slippage_amount=entry_record.slippage_amount,
        modeled_costs_per_unit=entry_record.modeled_costs_per_unit,
        coverage_note=coverage_note,
        fallback_applied=fallback_applied,
        outcome_kind=entry_record.outcome_kind,
        reason_code=entry_record.reason_code,
    )


__all__ = [
    "IntrabarOutcome",
    "SimulatorResult",
    "TradeRecord",
    "resolve_intrabar",
    "run",
]
