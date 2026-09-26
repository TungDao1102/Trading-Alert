"""Pure paper-loop dispatch (Phase 7, plan 07-01).

Per D-01/D-02: the paper loop is the realtime mirror of the backtest
simulator. It receives a feed sequence (WS kline events), applies the
double closed-candle gate (`x=True AND close_time_utc <= now_utc`),
and dispatches each closed event through the IDENTICAL Phase-4 core
plus Phase-5 risk call chain the backtest executes. No paper-local
setup logic, no simplified sizing, no cost-free path.

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 / Phase-6 D-05 purity
precedent. The WS surface lives behind `src/adapters/paper_ws.py`
(adapter-boundary isolation, RESEARCH §Pattern 1).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.backtest.costs import build_cost_model, modeled_costs_per_unit
from src.core.planner import plan
from src.core.strategy import evaluate
from src.core.types import (
    AccountState,
    Candle,
    MarketSnapshot,
)
from src.domain.registry import load_parameter_set
from src.domain.trade_plan import TradePlan
from src.risk.gating import evaluate_risk
from src.risk.portfolio import resolve_absolute_thresholds
from src.risk.types import ConstraintSnapshot, OpenPosition

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
    """Coerce a money/rate JSON field to Decimal, fail-closed (D-12)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be Decimal/str/int, got bool")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        return Decimal(value)
    raise TypeError(f"{field_name} must be Decimal/str/int, got {type(value).__name__}")


def _parse_utc_aware(raw: object, field_name: str) -> datetime:
    if not isinstance(raw, str):
        raise TypeError(f"{field_name} must be ISO str, got {type(raw).__name__}")
    value = datetime.fromisoformat(raw)
    _require_utc_aware(value, field_name)
    return value


def _parse_candle(row: dict[str, Any]) -> Candle:
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


def _signal_to_dict(signal: Any) -> dict[str, Any]:
    """Project a Signal to a canonical-JSON-safe dict."""
    out: dict[str, Any] = {}
    for k, v in signal.__dict__.items():
        if isinstance(v, Decimal):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _trade_plan_to_dict(plan_obj: TradePlan) -> dict[str, Any]:
    """Project a TradePlan to a canonical-JSON-safe dict."""
    out: dict[str, Any] = {}
    for k, v in plan_obj.__dict__.items():
        if isinstance(v, Decimal):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


# --------------------------------------------------------------------------- #
# Closed-candle gate — the determinism boundary (D-01).
# --------------------------------------------------------------------------- #


# Feed-freshness threshold (seconds). A WS kline event whose
# close_time_utc is older than this many seconds relative to now_utc
# is rejected as DATA_STALE before the engine chain runs. Default 60s
# matches the 1H cadence: a 1H candle that closed more than 60s ago
# is stale (the next 1H close is imminent). Exported for tests and
# downstream consumers (PATTERNS §Gates: explicit, exported).
STALENESS_THRESHOLD_SECONDS: int = 60

# Minimum closed bars required on each stream for the EMA200 warmup
# to clear. Below this, the feature layer emits WARMUP_INSUFFICIENT
# for every required feature; the paper loop short-circuits with the
# same reason code BEFORE evaluate() runs.
WARMUP_MIN_BARS: int = 200


def _is_closed_event(event: dict[str, Any], now_utc: datetime) -> bool:
    """Double gate: x=True AND close_time_utc <= now_utc.

    Per D-01: a WS kline event with `x=False` (forming update) MUST
    NOT reach evaluate. An event with `x=True` but `close_time_utc >
    now_utc` (future-close marker) MUST NOT reach evaluate. The gate
    is structural, not a log warning.
    """
    if not event.get("x", False):
        return False
    close_ms = int(event["T"])
    close_utc = datetime.fromtimestamp(close_ms / 1000, tz=now_utc.tzinfo)
    return close_utc <= now_utc


def _event_to_candle(event: dict[str, Any], symbol: str) -> Candle:
    """Project a WS kline event payload to a Candle.

    The WS payload uses Binance wire-format fields (t/T/o/h/l/c/v/n/x/q);
    the Candle uses the project's canonical field names. Decimal
    prices/quantities, UTC-aware datetimes.
    """
    from datetime import UTC

    open_ms = int(event["t"])
    close_ms = int(event["T"])
    open_utc = datetime.fromtimestamp(open_ms / 1000, tz=UTC)
    close_utc = datetime.fromtimestamp(close_ms / 1000, tz=UTC)
    return Candle(
        symbol=symbol,
        interval="1h",
        open_time_utc=open_utc,
        close_time_utc=close_utc,
        open=Decimal(str(event["o"])),
        high=Decimal(str(event["h"])),
        low=Decimal(str(event["l"])),
        close=Decimal(str(event["c"])),
        volume=Decimal(str(event["v"])),
    )


# --------------------------------------------------------------------------- #
# Feed gates — pre-engine fail-closed checks (D-02 / PATTERNS §Gates).
# --------------------------------------------------------------------------- #


def check_feature_validity(
    warmed_up_1h: list[Candle],
    warmed_up_4h: list[Candle],
) -> str | None:
    """Pre-engine warmup check. Returns the rejection reason code or None.

    Per D-02 fail-closed: if either stream has fewer closed bars than
    the EMA200 warmup window, the paper loop MUST NOT invoke evaluate().
    The engine would emit WARMUP_INSUFFICIENT anyway (the feature layer
    marks every required feature invalid), but firing the gate here
    short-circuits the chain so the rejection reason code is unambiguous
    (stage="feed_gate") and no compute_features work is wasted.
    """
    if len(warmed_up_1h) < WARMUP_MIN_BARS:
        return "WARMUP_INSUFFICIENT"
    if len(warmed_up_4h) < WARMUP_MIN_BARS:
        return "WARMUP_INSUFFICIENT"
    return None


def check_feed_freshness(
    event: dict[str, Any],
    now_utc: datetime,
) -> str | None:
    """Pre-engine staleness check. Returns the rejection reason code or None.

    Per D-02 fail-closed: a WS kline event whose close_time_utc is older
    than STALENESS_THRESHOLD_SECONDS relative to now_utc is rejected as
    DATA_STALE before the engine chain runs. The gate is per-event (not
    latched), so a fresh event after a stale event resumes evaluation
    without restart.
    """
    close_ms = int(event["T"])
    close_utc = datetime.fromtimestamp(close_ms / 1000, tz=now_utc.tzinfo)
    gap_seconds = (now_utc - close_utc).total_seconds()
    if gap_seconds > STALENESS_THRESHOLD_SECONDS:
        return "DATA_STALE"
    return None


# --------------------------------------------------------------------------- #
# Public entry point — run_paper_tick.
# --------------------------------------------------------------------------- #


def run_paper_tick(case_input: dict[str, Any]) -> dict[str, Any]:
    """Run the paper loop on a feed sequence.

    Returns a canonical-JSON-safe outcome dict with keys:
      - `signals`: list of Signal dicts emitted by the engine
      - `trade_plans`: list of TradePlan dicts emitted by the engine
      - `no_trade_records`: list of NO_TRADE records with reason_code
      - `feed_events_processed`: count of events that passed the gate
      - `feed_events_dropped`: count of events that failed the gate

    The function is a pure function of the input dict + injected
    `now_utc` (read from `case_input["now_utc"]`). No clock reads,
    no I/O, no randomness.
    """
    strategy_id = case_input["strategy_id"]
    strategy_version = case_input["strategy_version"]
    parameter_set_id = case_input["parameter_set_id"]
    symbol = case_input["symbol"]
    now_utc = _parse_utc_aware(case_input["now_utc"], "now_utc")
    ttl = timedelta(seconds=int(case_input["ttl_seconds"]))

    account_state = _parse_account_state(case_input["account_state"])
    constraint_snapshot = _parse_constraint_snapshot(case_input["constraint_snapshot"])
    cost_model = build_cost_model(case_input["cost_model"])
    open_positions = _parse_open_positions(case_input["open_positions"])
    daily_loss_quote = _coerce_money(case_input["daily_loss_quote"], "daily_loss_quote")

    warmed_up_1h = [_parse_candle(r) for r in case_input["warmed_up_1h"]]
    warmed_up_4h = [_parse_candle(r) for r in case_input["warmed_up_4h"]]
    feed_events = case_input["feed_events"]

    parameter_set = load_parameter_set(strategy_id, parameter_set_id)
    if parameter_set.strategy_version != strategy_version:
        raise ValueError(
            f"fixture strategy_version={strategy_version!r} != "
            f"registry strategy_version={parameter_set.strategy_version!r} "
            f"for {strategy_id}/{parameter_set_id}"
        )

    absolute_thresholds = resolve_absolute_thresholds(
        parameter_set=parameter_set.params,
        equity=account_state.equity,
    )

    # Sort warmed-up bars by close_time_utc ascending (deterministic).
    sorted_1h = sorted(warmed_up_1h, key=lambda c: c.close_time_utc)
    sorted_4h = sorted(warmed_up_4h, key=lambda c: c.close_time_utc)

    # Pre-engine feature-validity gate (D-02 fail-closed). If either
    # stream lacks the EMA200 warmup window, every event in this
    # feed sequence will be rejected — we short-circuit the whole
    # loop with a single feed_gate record (matches the gate contract:
    # the engine chain is never invoked with insufficient data).
    warmup_reject = check_feature_validity(sorted_1h, sorted_4h)

    signals: list[dict[str, Any]] = []
    trade_plans: list[dict[str, Any]] = []
    no_trade_records: list[dict[str, Any]] = []
    feed_events_processed = 0
    feed_events_dropped = 0

    for event in feed_events:
        if not _is_closed_event(event, now_utc):
            feed_events_dropped += 1
            continue
        feed_events_processed += 1

        # Pre-engine feature-validity gate — fires once for every
        # event when the warmed-up history is insufficient. Each
        # event is rejected individually so the per-bar audit trail
        # in no_trade_records carries the exact close_time_utc.
        if warmup_reject is not None:
            closed_candle = _event_to_candle(event, symbol)
            no_trade_records.append(
                {
                    "reason_code": warmup_reject,
                    "bar_close_utc": closed_candle.close_time_utc.isoformat(),
                    "stage": "feed_gate",
                }
            )
            continue

        # Pre-engine feed-freshness gate (D-02 fail-closed). Per-event,
        # not latched — a fresh event after a stale one resumes
        # evaluation without restart.
        stale_reject = check_feed_freshness(event, now_utc)
        if stale_reject is not None:
            closed_candle = _event_to_candle(event, symbol)
            no_trade_records.append(
                {
                    "reason_code": stale_reject,
                    "bar_close_utc": closed_candle.close_time_utc.isoformat(),
                    "stage": "feed_gate",
                }
            )
            continue

        # Build the closed candle from the WS event.
        closed_candle = _event_to_candle(event, symbol)

        # Build the snapshot: closed 1H bars (warmed-up + this event) +
        # closed 4H context bars (warmed-up, filtered to <= event close).
        closed_setup = sorted_1h + [closed_candle]
        closed_context = [c for c in sorted_4h if c.close_time_utc <= closed_candle.close_time_utc]
        snapshot = MarketSnapshot(
            symbol=symbol,
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
            no_trade_records.append(
                {
                    "reason_code": setup_result.reason_code,
                    "bar_close_utc": closed_candle.close_time_utc.isoformat(),
                    "stage": "strategy",
                }
            )
            continue

        signal = setup_result.signal
        assert signal is not None
        signals.append(_signal_to_dict(signal))

        # Planner.
        plan_result = plan(
            signal=signal,
            setup_candles=closed_setup,
            parameter_set=parameter_set,
            account_state=account_state,
            created_at_utc=closed_candle.close_time_utc,
        )
        if plan_result.is_no_trade:
            no_trade_records.append(
                {
                    "reason_code": plan_result.reason_code,
                    "bar_close_utc": closed_candle.close_time_utc.isoformat(),
                    "stage": "planner",
                    "signal_id": signal.signal_id,
                }
            )
            continue

        trade_plan = plan_result.trade_plan
        assert trade_plan is not None
        trade_plans.append(_trade_plan_to_dict(trade_plan))

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
            now_utc=closed_candle.close_time_utc,
            ttl=ttl,
            modeled_costs_per_unit=modeled_costs,
            minimum_risk_utilization_after_rounding=Decimal(
                str(parameter_set.params["minimum_risk_utilization_after_rounding"])
            ),
            parameter_set=absolute_thresholds,
        )
        if verdict.is_no_trade:
            no_trade_records.append(
                {
                    "reason_code": verdict.reason_code,
                    "bar_close_utc": closed_candle.close_time_utc.isoformat(),
                    "stage": "risk",
                    "signal_id": signal.signal_id,
                    "trade_plan_id": trade_plan.trade_plan_id,
                }
            )
            continue

        # Risk passed — emit a paper record (tracer slice: no simulated
        # fill yet; Phase 7 plan 07-02 adds the simulated-fill path).
        no_trade_records.append(
            {
                "reason_code": "OK",
                "bar_close_utc": closed_candle.close_time_utc.isoformat(),
                "stage": "risk_passed",
                "signal_id": signal.signal_id,
                "trade_plan_id": trade_plan.trade_plan_id,
            }
        )

    return {
        "signals": signals,
        "trade_plans": trade_plans,
        "no_trade_records": no_trade_records,
        "feed_events_processed": feed_events_processed,
        "feed_events_dropped": feed_events_dropped,
    }


__all__ = ["run_paper_tick", "STALENESS_THRESHOLD_SECONDS", "WARMUP_MIN_BARS"]
