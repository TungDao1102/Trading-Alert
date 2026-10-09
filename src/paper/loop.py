"""Pure paper-loop dispatch (Phase 7, plan 07-01).

Per D-01/D-02: the paper loop is the realtime mirror of the backtest
simulator. It receives a feed sequence (WS kline events), applies the
double closed-candle gate (`x=True AND close_time_utc <= now_utc`),
and dispatches each closed event through the IDENTICAL Phase-4 core
plus Phase-5 risk call chain the backtest executes. No paper-local
setup logic, no simplified sizing, no cost-free path.

The module imports nothing from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic, mirroring the Phase-4 D-10 / Phase-5 D-05 /
Phase-6 D-05 purity precedent. Beyond stdlib, Decimal and
`src/core/_decimal.py` it imports the project-owned `src.backtest`,
`src.core`, `src.domain`, `src.risk` and `src.paper.freeze` surfaces
(the last pulls `structlog` for its own logging). The WS surface lives
behind `src/adapters/paper_ws.py` (adapter-boundary isolation, RESEARCH
§Pattern 1).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from src.backtest.binding import assert_sizing_costs_bind_registry
from src.backtest.costs import (
    CostModel,
    build_cost_model,
    cost_rates_from_model,
    guard_rates_from_params,
)
from src.core.planner import plan
from src.core.strategy import evaluate
from src.core.types import (
    AccountState,
    Candle,
    MarketSnapshot,
)
from src.domain.registry import ParameterSet
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.paper.freeze import (
    load_parameter_set_at_root,
    pin_stream_epoch,
    require_bool_flag,
    resolve_registry_root,
)
from src.risk.gating import evaluate_risk
from src.risk.portfolio import resolve_absolute_thresholds
from src.risk.types import ConstraintSnapshot, OpenPosition, PortfolioVerdict

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


def _ms_to_utc(ms: int) -> datetime:
    """Convert integer millisecond epoch to tz-aware UTC (WR-01).

    Exact timedelta arithmetic — never `ms / 1000` float division,
    which loses sub-millisecond precision on large epochs and
    escapes the no-float AST guard.
    """
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=ms)


def _parse_event_close(event: dict[str, Any]) -> datetime:
    """Parse and validate a WS event's close time, UTC-anchored (WR-14).

    Single owner of the `event["T"]` parse (previously parsed three
    times per event with bare KeyError/ValueError). Missing or
    non-numeric `T` raises ValueError with an explicit message;
    conversion is anchored to UTC, never to the caller's tz.
    """
    try:
        close_ms = int(event["T"])
    except KeyError as exc:
        raise ValueError("event missing 'T' (close-time ms)") from exc
    except (TypeError, ValueError) as exc:
        raise ValueError(f"event 'T' is not numeric: {event.get('T')!r}") from exc
    return _ms_to_utc(close_ms)


def _is_closed_event(event: dict[str, Any], now_utc: datetime) -> bool:
    """Double gate: x=True AND close_time_utc <= now_utc.

    Per D-01: a WS kline event with `x=False` (forming update) MUST
    NOT reach evaluate. An event with `x=True` but `close_time_utc >
    now_utc` (future-close marker) MUST NOT reach evaluate. The gate
    is structural, not a log warning. Malformed events (missing `x`
    defaults False; unparsable `T`) are dropped, counted with the
    gated drops.
    """
    if not event.get("x", False):
        return False
    try:
        close_utc = _parse_event_close(event)
    except ValueError:
        return False
    return close_utc <= now_utc


def _event_to_candle(event: dict[str, Any], symbol: str, interval: str = "1h") -> Candle:
    """Project a WS kline event payload to a Candle.

    The WS payload uses Binance wire-format fields (t/T/o/h/l/c/v/n/x/q);
    the Candle uses the project's canonical field names. Decimal
    prices/quantities, UTC-aware datetimes.

    `interval` is explicit per event (CR-08): the caller passes
    `event.get("interval", "1h")` so a 4h close is never mislabeled
    as a 1h bar. Only "1h"/"4h" are accepted (fail-closed).
    """
    if interval not in ("1h", "4h"):
        raise ValueError(f"unsupported event interval {interval!r}; expected '1h' or '4h'")
    try:
        open_ms = int(event["t"])
    except KeyError as exc:
        raise ValueError("event missing 't' (open-time ms)") from exc
    open_utc = _ms_to_utc(open_ms)
    close_utc = _parse_event_close(event)
    return Candle(
        symbol=symbol,
        interval=interval,
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
    without restart. Malformed events propagate ValueError (fail-closed,
    never silently fresh).
    """
    close_utc = _parse_event_close(event)
    gap_seconds = (now_utc - close_utc).total_seconds()
    if gap_seconds > STALENESS_THRESHOLD_SECONDS:
        return "DATA_STALE"
    return None


# --------------------------------------------------------------------------- #
# Typed per-bar evaluation — the body of run_paper_tick, extracted (D-02).
# --------------------------------------------------------------------------- #

# Stages a closed 1h bar can end at, in chain order (strategy -> planner -> risk -> risk_passed).
BAR_STAGES: tuple[str, ...] = ("strategy", "planner", "risk", "risk_passed")


@dataclass(frozen=True)
class BarContext:
    """Everything the per-bar chain needs besides the bar and its windows (D-02).

    One context is shared by every bar of a run: the symbol, the registry parameter set, the
    account and constraint snapshots, the cost model, the portfolio state the risk gates read,
    the plan TTL and the absolute portfolio thresholds (already converted from registry rates).
    """

    symbol: str
    strategy_version: str
    parameter_set: ParameterSet
    account_state: AccountState
    constraint_snapshot: ConstraintSnapshot
    cost_model: CostModel
    open_positions: Sequence[OpenPosition]
    daily_loss_quote: Decimal | None
    ttl: timedelta
    absolute_thresholds: dict[str, Any]


@dataclass(frozen=True)
class BarOutcome:
    """The typed result of one closed 1h bar through evaluate -> plan -> evaluate_risk.

    `stage` is where the chain ended (`BAR_STAGES`). `signal` is set from the planner stage on,
    `trade_plan` and `verdict` from the risk stage on; a strategy-stage NO_TRADE carries none of
    the three. `reason_code` is the stage's reason ("OK" for `risk_passed`). `regime` is the 4h
    regime verdict the strategy resolved, or None when it stopped before the regime was known.
    """

    closed_candle: Candle
    stage: str
    reason_code: str
    signal: Signal | None = None
    trade_plan: TradePlan | None = None
    verdict: PortfolioVerdict | None = None
    regime: str | None = None

    def __post_init__(self) -> None:
        if self.stage not in BAR_STAGES:
            raise ValueError(f"BarOutcome: unknown stage {self.stage!r}; expected {BAR_STAGES}")
        _require_non_empty(self.reason_code, "reason_code")


def evaluate_closed_bar(
    context: BarContext,
    closed_candle: Candle,
    setup_candles: list[Candle],
    context_candles: list[Candle],
) -> BarOutcome:
    """Run one closed 1h bar through the shared strategy, planner and risk chain.

    `setup_candles` is the closed 1h series ending at `closed_candle` and `context_candles` the
    closed 4h series at or before its close; the caller cuts the windows (the paper tick passes
    its whole series, the runtime and the decision surface pass the engine windows). Pure: no
    clock, no I/O. The feed gates, warm-up gate and duplicate-bar handling stay with the caller.
    """
    snapshot = MarketSnapshot(
        symbol=context.symbol,
        setup_candles=setup_candles,
        context_candles=context_candles,
        source_timeframe="1h",
    )

    # Strategy gate.
    setup_result = evaluate(
        snapshot=snapshot,
        account_state=context.account_state,
        strategy_version=context.strategy_version,
        parameter_set=context.parameter_set,
    )
    if setup_result.is_no_trade:
        return BarOutcome(
            closed_candle=closed_candle,
            stage="strategy",
            reason_code=setup_result.reason_code,
            regime=setup_result.regime,
        )

    signal = setup_result.signal
    assert signal is not None

    # Planner.
    plan_result = plan(
        signal=signal,
        setup_candles=setup_candles,
        parameter_set=context.parameter_set,
        account_state=context.account_state,
        created_at_utc=closed_candle.close_time_utc,
    )
    if plan_result.is_no_trade:
        return BarOutcome(
            closed_candle=closed_candle,
            stage="planner",
            reason_code=plan_result.reason_code,
            signal=signal,
            regime=setup_result.regime,
        )

    trade_plan = plan_result.trade_plan
    assert trade_plan is not None

    # Risk pipeline.
    cost_rates = cost_rates_from_model(context.cost_model)
    min_stop_distance_rate, max_cost_to_risk = guard_rates_from_params(context.parameter_set.params)
    verdict = evaluate_risk(
        trade_plan=trade_plan,
        candidate_position_side=signal.direction,
        account_state=context.account_state,
        constraint_snapshot=context.constraint_snapshot,
        open_positions=context.open_positions,
        daily_loss_quote=context.daily_loss_quote,
        now_utc=closed_candle.close_time_utc,
        ttl=context.ttl,
        cost_rates=cost_rates,
        min_stop_distance_rate=min_stop_distance_rate,
        max_cost_to_risk=max_cost_to_risk,
        minimum_risk_utilization_after_rounding=Decimal(
            str(context.parameter_set.params["minimum_risk_utilization_after_rounding"])
        ),
        parameter_set=context.absolute_thresholds,
    )
    if verdict.is_no_trade:
        return BarOutcome(
            closed_candle=closed_candle,
            stage="risk",
            reason_code=verdict.reason_code,
            signal=signal,
            trade_plan=trade_plan,
            verdict=verdict,
            regime=setup_result.regime,
        )

    # Risk passed — the tick emits a paper record (no simulated fill here; the runtime adds it).
    return BarOutcome(
        closed_candle=closed_candle,
        stage="risk_passed",
        reason_code="OK",
        signal=signal,
        trade_plan=trade_plan,
        verdict=verdict,
        regime=setup_result.regime,
    )


def _outcome_to_record(outcome: BarOutcome) -> dict[str, Any]:
    """Project a BarOutcome to the exact `no_trade_records` dict the tick has always emitted."""
    record: dict[str, Any] = {
        "reason_code": outcome.reason_code,
        "bar_close_utc": outcome.closed_candle.close_time_utc.isoformat(),
        "stage": outcome.stage,
    }
    if outcome.stage == "strategy":
        return record
    assert outcome.signal is not None
    record["signal_id"] = outcome.signal.signal_id
    if outcome.stage == "planner":
        return record
    assert outcome.trade_plan is not None
    record["trade_plan_id"] = outcome.trade_plan.trade_plan_id
    return record


# --------------------------------------------------------------------------- #
# Public entry point — run_paper_tick.
# --------------------------------------------------------------------------- #


def run_paper_tick(
    case_input: dict[str, Any],
    *,
    allow_unrationalized: bool = False,
) -> dict[str, Any]:
    """Run the paper loop on a feed sequence.

    The per-call gate runs first, on every call, before any candle is parsed or feed event
    read: the registry root is resolved once, the parameter set is loaded from it, its
    strategy_version checked and `pin_stream_epoch` called with that same root, so the gate
    and the loop judge one file. A set with a missing or incomplete rationale or a
    PLACEHOLDER key raises `UnrationalizedParameterSet` (D-16, D-27); a set without
    rationale tables needs an exact-hash entry in the approved paper-start allowlist of
    `src/paper/freeze.py`, which is empty by the user's decision at checkpoint 15-17-01.
    `allow_unrationalized` is for tests only; src/ never turns it on. The pinned epoch is
    used here only for its hash and is not persisted: the runtime (plan 16-22) adds a
    once-per-process start gate and pins the epoch once.

    Returns a canonical-JSON-safe outcome dict with keys:
      - `signals`: list of Signal dicts emitted by the engine
      - `trade_plans`: list of TradePlan dicts emitted by the engine
      - `no_trade_records`: list of NO_TRADE records with reason_code
      - `feed_events_processed`: count of events that passed the gate
      - `feed_events_dropped`: count of events that failed the gate

    Apart from the registry reads below, the function is a pure function of the input dict +
    injected `now_utc` (read from `case_input["now_utc"]`): no clock reads, no randomness.
    Its outcome also depends on the registry files under the resolved registry root and on
    the approved paper-start allowlist of `src/paper/freeze.py` (module-level, read per call).

    Raises:
        TypeError: `allow_unrationalized` is not a bool (checked first).
        UnregisteredParameterSet: the parameter set file does not exist or an id is not a
            safe registry path segment.
        ValueError: `case_input["strategy_version"]` differs from the registry's, or the
            hash the gate judged differs from the hash the loop loaded. The strategy_version
            check runs BEFORE the rationale gate, so a stale fixture version on a refused set
            raises this `ValueError`, not `UnrationalizedParameterSet`. This order is the
            contract (moving it would change which exception a caller sees). A caller that
            maps `UnrationalizedParameterSet` to "refused by policy" must catch both.
        UnrationalizedParameterSet: rationale missing or incomplete, a PLACEHOLDER key, or no
            exact-hash allowlist entry for a set without rationale tables.
        KeyError: a cost-slice key is missing from the registry set (fail closed, never
            translated, 07.1 D-02), or a required `case_input` field is absent once the
            gate has passed.
    """
    require_bool_flag(allow_unrationalized)  # review WR-01: only a real bool, before anything else
    strategy_id = case_input["strategy_id"]
    strategy_version = case_input["strategy_version"]
    parameter_set_id = case_input["parameter_set_id"]
    now_utc = _parse_utc_aware(case_input["now_utc"], "now_utc")

    # Per-call gate (G-15-11): nothing below this block runs for a refused set. The registry
    # root is resolved ONCE and used for both the load and the gate (review IN-05).
    registry_root = resolve_registry_root()
    parameter_set = load_parameter_set_at_root(strategy_id, parameter_set_id, registry_root)
    if parameter_set.strategy_version != strategy_version:
        raise ValueError(
            f"fixture strategy_version={strategy_version!r} != "
            f"registry strategy_version={parameter_set.strategy_version!r} "
            f"for {strategy_id}/{parameter_set_id}"
        )
    epoch = pin_stream_epoch(
        strategy_id=strategy_id,
        parameter_set_id=parameter_set_id,
        opened_at_utc=now_utc,
        registry_root=registry_root,
        allow_unrationalized=allow_unrationalized,
    )
    if epoch.parameter_set_hash != parameter_set.parameter_set_hash:
        raise ValueError(
            f"per-call gate judged parameter_set_hash={epoch.parameter_set_hash!r} but the "
            f"loop loaded parameter_set_hash={parameter_set.parameter_set_hash!r} "
            f"for {strategy_id}/{parameter_set_id}"
        )

    symbol = case_input["symbol"]
    ttl = timedelta(seconds=int(case_input["ttl_seconds"]))

    account_state = _parse_account_state(case_input["account_state"])
    constraint_snapshot = _parse_constraint_snapshot(case_input["constraint_snapshot"])
    cost_model = build_cost_model(case_input["cost_model"])
    open_positions = _parse_open_positions(case_input["open_positions"])
    daily_loss_quote = _coerce_money(case_input["daily_loss_quote"], "daily_loss_quote")

    warmed_up_1h = [_parse_candle(r) for r in case_input["warmed_up_1h"]]
    warmed_up_4h = [_parse_candle(r) for r in case_input["warmed_up_4h"]]
    feed_events = case_input["feed_events"]

    # 12-REVIEW WR-03: refuse a fixture cost model the registry set does not pin.
    assert_sizing_costs_bind_registry(parameter_set, cost_model)

    absolute_thresholds = resolve_absolute_thresholds(
        parameter_set=parameter_set.params,
        equity=account_state.equity,
    )

    bar_context = BarContext(
        symbol=symbol,
        strategy_version=strategy_version,
        parameter_set=parameter_set,
        account_state=account_state,
        constraint_snapshot=constraint_snapshot,
        cost_model=cost_model,
        open_positions=tuple(open_positions),
        daily_loss_quote=daily_loss_quote,
        ttl=ttl,
        absolute_thresholds=absolute_thresholds,
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

    # Open times already in warmed history (WR-04 dedup seed); extended
    # with each accepted 1h close so re-delivered bars in the same call
    # are rejected as DUPLICATE_BAR instead of re-entering evaluate().
    seen_open_times = {c.open_time_utc for c in sorted_1h}
    # 4h closes accepted during this call extend the context window for
    # later 1h events (CR-08: 4h updates context only).
    extra_context: list[Candle] = []

    for event in feed_events:
        if not _is_closed_event(event, now_utc):
            feed_events_dropped += 1
            continue
        feed_events_processed += 1
        interval = event.get("interval", "1h")

        # Pre-engine feed-freshness gate FIRST (WR-03: the liveness
        # signal wins — a stale feed must report DATA_STALE even when
        # the stream is also under-warmed).
        stale_reject = check_feed_freshness(event, now_utc)
        if stale_reject is not None:
            closed_candle = _event_to_candle(event, symbol, interval)
            no_trade_records.append(
                {
                    "reason_code": stale_reject,
                    "bar_close_utc": closed_candle.close_time_utc.isoformat(),
                    "stage": "feed_gate",
                }
            )
            continue

        # Pre-engine feature-validity gate — fires once for every
        # event when the warmed-up history is insufficient. Each
        # event is rejected individually so the per-bar audit trail
        # in no_trade_records carries the exact close_time_utc.
        if warmup_reject is not None:
            closed_candle = _event_to_candle(event, symbol, interval)
            no_trade_records.append(
                {
                    "reason_code": warmup_reject,
                    "bar_close_utc": closed_candle.close_time_utc.isoformat(),
                    "stage": "feed_gate",
                }
            )
            continue

        # 4h closes update context only (CR-08) — never appended to
        # the 1h setup series that feeds EMA/signal evaluation.
        if interval == "4h":
            context_candle = _event_to_candle(event, symbol, "4h")
            extra_context.append(context_candle)
            no_trade_records.append(
                {
                    "reason_code": "CONTEXT_BAR",
                    "bar_close_utc": context_candle.close_time_utc.isoformat(),
                    "stage": "feed_gate",
                }
            )
            continue

        # Build the closed candle from the WS event.
        closed_candle = _event_to_candle(event, symbol, "1h")

        # Re-delivered bars are not re-evaluated (WR-04): after a
        # reconnect, REST backfill or a WS duplicate can re-deliver an
        # open_time already in warmed history.
        if closed_candle.open_time_utc in seen_open_times:
            no_trade_records.append(
                {
                    "reason_code": "DUPLICATE_BAR",
                    "bar_close_utc": closed_candle.close_time_utc.isoformat(),
                    "stage": "feed_gate",
                }
            )
            continue
        seen_open_times.add(closed_candle.open_time_utc)

        # Closed 1H bars (warmed-up + this event) + closed 4H context bars (warmed-up + this
        # call's 4h closes, filtered to <= event close). The whole series is passed; the
        # runtime and the decision surface cut the engine windows themselves.
        closed_setup = sorted_1h + [closed_candle]
        closed_context = [
            c for c in sorted_4h + extra_context if c.close_time_utc <= closed_candle.close_time_utc
        ]
        outcome = evaluate_closed_bar(bar_context, closed_candle, closed_setup, closed_context)
        if outcome.signal is not None:
            signals.append(_signal_to_dict(outcome.signal))
        if outcome.trade_plan is not None:
            trade_plans.append(_trade_plan_to_dict(outcome.trade_plan))
        no_trade_records.append(_outcome_to_record(outcome))

    return {
        "signals": signals,
        "trade_plans": trade_plans,
        "no_trade_records": no_trade_records,
        "feed_events_processed": feed_events_processed,
        "feed_events_dropped": feed_events_dropped,
    }


__all__ = [
    "BAR_STAGES",
    "STALENESS_THRESHOLD_SECONDS",
    "WARMUP_MIN_BARS",
    "BarContext",
    "BarOutcome",
    "evaluate_closed_bar",
    "run_paper_tick",
]
