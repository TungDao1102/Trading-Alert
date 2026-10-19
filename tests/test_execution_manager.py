"""Execution manager tests (Phase 9, plan 09-01).

Per D-01/D-05: the execution manager is a pure orchestration function
that gates every placement on the Phase-8 approval binding, then runs
the identical Phase-5 risk pipeline, then calls the adapter placement
surface in fixed order. The tests use a `FakeExecutionAdapter` that
records every call so the placement sequence is byte-exact and
deterministic.

The four behaviors pinned here:

  1. Happy path: approved in-date plan with PASS risk verdict yields
     exactly one `place_entry` call (LIMIT, GTC, quantized qty,
     zone-derived limit price, x- EN id) followed by one
     `place_algo_protective` call (CONDITIONAL STOP_MARKET SL,
     close_position True, no quantity, xa- SL id).
  2. Stale/expired plan yields no adapter calls and an UNAPPROVABLE
     outcome with reason code.
  3. Risk NO_TRADE verdict yields no adapter calls and the risk reason
     code preserved byte-identically.
  4. Ambiguous `place_entry` response triggers `query_order_by_client`
     first; retry occurs only when the probe confirms absence.

The tests load the golden fixture pair
(`tests/fixtures/phase9/placement_sequences/{input,expected}.json`) and
assert the recorded adapter call sequence matches the expected
sequence byte-for-byte.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.domain.enums import KillGateState

from tests.support.intent_store_fakes import AlwaysWinsIntentStore, InMemoryExecutionIntentStore

PHASE9_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase9"
PLACEMENT_FIXTURE_DIR = PHASE9_FIXTURES_DIR / "placement_sequences"


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _load_input() -> dict[str, Any]:
    return json.loads((PLACEMENT_FIXTURE_DIR / "input.json").read_text(encoding="utf-8"))


def _load_expected() -> dict[str, Any]:
    return json.loads((PLACEMENT_FIXTURE_DIR / "expected.json").read_text(encoding="utf-8"))


def _parse_utc(raw: str) -> datetime:
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise ValueError(f"naive datetime in fixture: {raw!r}")
    return value.astimezone(UTC)


def _coerce_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        return Decimal(value)
    if isinstance(value, int):
        return Decimal(value)
    raise TypeError(f"{field_name} must be Decimal/str/int, got {type(value).__name__}")


# --------------------------------------------------------------------------- #
# FakeExecutionAdapter — records every call for byte-exact assertions.
# --------------------------------------------------------------------------- #


def _mark_reading_for(case_input: dict[str, Any], **overrides: Any) -> Any:
    """The `MarkPriceReading` the fake answers: the fixture mark price, `mark_age_ms` old."""
    from src.adapters.binance_public import MarkPriceReading

    live = case_input["live"]
    values: dict[str, Any] = {
        "symbol": case_input["symbol"],
        "mark_price": _coerce_decimal(live["mark_price"], "mark_price"),
        "exchange_time_utc": _parse_utc(case_input["now_utc"])
        - timedelta(milliseconds=int(live["mark_age_ms"])),
    }
    values.update(overrides)
    return MarkPriceReading(**values)


# The three reads that precede the position-mode read and the placement (plan 19-13, gate 5e).
PRE_PLACEMENT_READS = [
    "get_mark_price",
    "snapshot_open_normal_orders",
    "snapshot_open_algo_orders",
]


class FakeExecutionAdapter:
    """In-memory adapter that records every placement call.

    Mirrors the four-method surface the real `BinanceUsdmAdapter` will
    expose in Task 3 (`place_entry`, `place_algo_protective`,
    `query_order_by_client`, `get_position_mode`). The fake never
    touches the network — it returns canned responses and records the
    call sequence so the test can assert byte-exact ordering.
    """

    def __init__(
        self,
        *,
        entry_response: Any | None = None,
        algo_response: Any | None = None,
        query_response: Any | None = None,
        position_mode: str = "ONE_WAY",
        case_input: dict[str, Any] | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        # Plan 19-13 pre-placement reads: a fresh mark price inside the zone, no open orders.
        # `case_input` anchors the default reading's exchange time on the case's own clock.
        case = case_input if case_input is not None else _load_input()
        self.mark_reading: Any = _mark_reading_for(case)
        self.mark_exception: BaseException | None = None
        self.open_normal_orders: list[Any] = []
        self.open_algo_orders: list[Any] = []
        self.normal_orders_exception: BaseException | None = None
        self.algo_orders_exception: BaseException | None = None
        # Default to a non-None entry response so the happy path doesn't
        # trigger the query-before-retry path. Tests that want to test
        # the ambiguous path explicitly pass entry_response=None.
        self._entry_response = (
            entry_response
            if entry_response is not None
            else {"order_id": "default_entry_001", "status": "NEW"}
        )
        self._algo_response = (
            algo_response
            if algo_response is not None
            else {"algo_id": "default_algo_001", "algo_status": "NEW"}
        )
        self._query_response = query_response
        self._position_mode = position_mode
        # Exceptions raised by successive `place_entry` / probe calls
        # (popped front-first); empty means "return the canned response".
        self.entry_exceptions: list[BaseException] = []
        self.query_exceptions: list[BaseException] = []
        self.query_responses: list[Any] = []
        # Simulated exchange algo state (client_algo_id -> algo_status).
        self.existing_algo_status: dict[str, str] = {}

    @staticmethod
    def _bind_real(method_name: str, kwargs: dict[str, Any]) -> None:
        """Contract guard (09-REVIEW WR-12): kwargs must bind against the
        REAL `BinanceUsdmAdapter` method signature."""
        import inspect

        from src.adapters.binance_usdm import BinanceUsdmAdapter

        inspect.signature(getattr(BinanceUsdmAdapter, method_name)).bind(None, **kwargs)

    async def get_mark_price(self, **kwargs: Any) -> Any:
        self._bind_real("get_mark_price", kwargs)
        self.calls.append({"method": "get_mark_price", "kwargs": dict(kwargs)})
        if self.mark_exception is not None:
            raise self.mark_exception
        return self.mark_reading

    async def snapshot_open_normal_orders(self, **kwargs: Any) -> Any:
        self._bind_real("snapshot_open_normal_orders", kwargs)
        self.calls.append({"method": "snapshot_open_normal_orders", "kwargs": dict(kwargs)})
        if self.normal_orders_exception is not None:
            raise self.normal_orders_exception
        return list(self.open_normal_orders)

    async def snapshot_open_algo_orders(self, **kwargs: Any) -> Any:
        self._bind_real("snapshot_open_algo_orders", kwargs)
        self.calls.append({"method": "snapshot_open_algo_orders", "kwargs": dict(kwargs)})
        if self.algo_orders_exception is not None:
            raise self.algo_orders_exception
        return list(self.open_algo_orders)

    async def place_entry(self, **kwargs: Any) -> Any:
        self._bind_real("place_entry", kwargs)
        self.calls.append({"method": "place_entry", "kwargs": dict(kwargs)})
        if self.entry_exceptions:
            raise self.entry_exceptions.pop(0)
        return self._entry_response

    async def place_algo_protective(self, **kwargs: Any) -> Any:
        self._bind_real("place_algo_protective", kwargs)
        self.calls.append({"method": "place_algo_protective", "kwargs": dict(kwargs)})
        return self._algo_response

    async def query_algo_order_by_client(self, **kwargs: Any) -> Any:
        from src.adapters.binance_usdm import AlgoOrderProbe

        self._bind_real("query_algo_order_by_client", kwargs)
        self.calls.append({"method": "query_algo_order_by_client", "kwargs": dict(kwargs)})
        status = self.existing_algo_status.get(kwargs["client_algo_id"])
        return AlgoOrderProbe(
            client_algo_id=kwargs["client_algo_id"],
            found=status is not None,
            algo_status=status,
            update_time_utc=None,
        )

    async def cancel_normal_order(self, **kwargs: Any) -> Any:
        self._bind_real("cancel_normal_order", kwargs)
        self.calls.append({"method": "cancel_normal_order", "kwargs": dict(kwargs)})
        return None

    async def query_order_by_client(self, **kwargs: Any) -> Any:
        self._bind_real("query_order_by_client", kwargs)
        self.calls.append({"method": "query_order_by_client", "kwargs": dict(kwargs)})
        if self.query_exceptions:
            raise self.query_exceptions.pop(0)
        if self.query_responses:
            return self.query_responses.pop(0)
        return self._query_response

    async def get_position_mode(self) -> Any:
        from src.adapters.binance_usdm import PositionModeResult

        self.calls.append({"method": "get_position_mode", "kwargs": {}})
        if self._position_mode not in ("ONE_WAY", "HEDGE"):
            raise RuntimeError("position mode unavailable")
        # The REAL adapter returns a PositionModeResult, not a string.
        return PositionModeResult(dual_side_position=self._position_mode == "HEDGE")


class FakeJournal:
    """In-memory journal recording every event."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)


class RecordingSafeModeController:
    """Duck-typed SafeModeController recording every SAFE_MODE entry."""

    def __init__(self, *, in_safe_mode: bool = False) -> None:
        self.entered_reasons: list[str] = []
        self.in_safe_mode = in_safe_mode

    def enter_safe_mode(self, *, reason: str, now_utc: Any = None) -> None:
        self.entered_reasons.append(reason)
        self.in_safe_mode = True

    def guard_new_entries(self, trade_plan: Any) -> Any:
        from src.reconcile.safe_mode import SafeModeVerdict

        if self.in_safe_mode:
            return SafeModeVerdict(is_no_trade=True, reason_code="RECONCILIATION_REQUIRED")
        return SafeModeVerdict(is_no_trade=False, reason_code=None)


class StubProtectionRegistry:
    """`ProtectionRegistry` stub: `blocks_new_entries` answers a fixed value (plan 19-13)."""

    def __init__(self, *, blocks: bool = False) -> None:
        self.blocks = blocks
        self.block_checks = 0

    def blocks_new_entries(self) -> bool:
        self.block_checks += 1
        return self.blocks

    def register_resting_entry(self, entry: Any) -> None:  # pragma: no cover - unused here
        raise AssertionError("the manager must not register an entry in plan 19-13")

    def protection_of(self, plan_hash: str) -> Any:  # pragma: no cover - unused here
        return None


def _live_wiring(*, case_input: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    """The required live-safety collaborators for `execute_approved_plan`.

    09-REVIEW CR-07/CR-09: SAFE_MODE (and the other live gates) are
    required arguments — tests wire recording doubles explicitly. Plan 19-13 adds the
    `live_context` bundle (Signal, constraint snapshot, TEST_ONLY limits, registry stub).
    """
    case = case_input if case_input is not None else _load_input()
    wiring: dict[str, Any] = {
        "safe_mode_controller": RecordingSafeModeController(),
        "journal": FakeJournal(),
        "enablement": _enabled_controller(),
        "gate_kwargs": _build_gate_kwargs(case),
        # Fresh in-memory store per call: every test keeps its one-call semantics.
        "intent_store": InMemoryExecutionIntentStore(),
        "live_context": _build_live_context(case),
    }
    wiring.update(overrides)
    return wiring


def _passing_health_verdict() -> Any:
    """A complete, all-PASS `HealthVerdict` (09-REVIEW WR-08)."""
    from src.ops.health import ALL_CHECK_NAMES, HealthCheckResult, run_health_checks

    observed = datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
    return run_health_checks(
        results=[
            HealthCheckResult(check_name=name, status="PASS", detail="ok", observed_at_utc=observed)
            for name in ALL_CHECK_NAMES
        ]
    )


def _enabled_controller() -> Any:
    """A real `LiveEnablementController`, explicitly operator-enabled."""
    from src.execution.enablement import LiveEnablementController

    controller = LiveEnablementController(journal=FakeJournal())
    controller.enable(
        operator_id="operator_alpha",
        now_utc=datetime(2026, 9, 19, 10, 0, tzinfo=UTC),
        health_verdict=_passing_health_verdict(),
        kill_gate_state=KillGateState.WITHIN_BUDGET,
    )
    return controller


def _build_gate_kwargs(case_input: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """The live-state `decide_placement` inputs (all gates PASS).

    09-REVIEW WR-05: everything else the gates judge is derived by the
    manager from the risk inputs / verdict.
    """
    gate_kwargs: dict[str, Any] = {
        "open_algo_count": 0,
        "planned_leg_count": 4,
        "positions_reconciled": True,
    }
    gate_kwargs.update(overrides)
    return gate_kwargs


# --------------------------------------------------------------------------- #
# Fixture builders — build the inputs the manager expects.
# --------------------------------------------------------------------------- #


def _plan_hash_of(case_input: dict[str, Any]) -> str:
    """The plan hash re-derived from the fixture's plan fields (plan 19-13, D-01).

    The binding refuses a hash that the planner's algorithm does not reproduce, so the fixture's
    stored `plan_hash` is only a pin (`test_fixture_plan_hash_is_the_rederived_hash`); every
    builder takes the hash from the fields, so a test that edits a hashed field stays consistent.
    """
    from src.core.planner import plan_hash_from_fields

    return plan_hash_from_fields(
        signal_id=case_input["signal_id"],
        entry_min_price=_coerce_decimal(case_input["entry_min_price"], "entry_min_price"),
        entry_max_price=_coerce_decimal(case_input["entry_max_price"], "entry_max_price"),
        stop_loss_price=_coerce_decimal(case_input["stop_loss_price"], "stop_loss_price"),
        take_profit_json=case_input["take_profit_json"],
        invalidation_rule_json=case_input["invalidation_rule_json"],
        expiry_utc=_parse_utc(case_input["expiry_utc"]),
    )


def _build_signal(case_input: dict[str, Any], **overrides: Any) -> Any:
    """The persisted Signal the fixture plan was built from (BTCUSDT LONG)."""
    from src.domain.enums import SignalStatus
    from src.domain.signal import Signal

    raw = case_input["signal"]
    values: dict[str, Any] = {
        "signal_id": case_input["signal_id"],
        "strategy_id": raw["strategy_id"],
        "strategy_version": case_input["strategy_version"],
        "parameter_set_id": case_input["parameter_set_id"],
        "parameter_set_hash": case_input["parameter_set_hash"],
        "symbol": case_input["symbol"],
        "direction": case_input["candidate_position_side"],
        "setup_type": raw["setup_type"],
        "source_timeframe": raw["source_timeframe"],
        "source_candle_close_utc": _parse_utc(raw["source_candle_close_utc"]),
        "detected_at_utc": _parse_utc(raw["detected_at_utc"]),
        "status": SignalStatus.APPROVED,
        "expires_at_utc": _parse_utc(raw["expires_at_utc"]),
    }
    values.update(overrides)
    return Signal(**values)


def _build_plan_snapshot(case_input: dict[str, Any], **overrides: Any) -> Any:
    """The per-plan constraint snapshot (MARK_PRICE working type) for the fixture plan."""
    import dataclasses

    from src.execution.constraint_snapshot import (
        ExchangeFilterExtras,
        build_plan_constraint_snapshot,
    )

    snapshot = build_plan_constraint_snapshot(
        case_input["trade_plan_id"],
        _build_constraint_snapshot(case_input),
        ExchangeFilterExtras(),
        None,
        "MARK_PRICE",
        captured_at_utc=_parse_utc(case_input["metadata_observed_at_utc"]),
    )
    return dataclasses.replace(snapshot, **overrides) if overrides else snapshot


def _build_live_context(case_input: dict[str, Any], **overrides: Any) -> Any:
    """The `LivePlacementContext` for the fixture plan with the TEST_ONLY execution limits."""
    from src.execution.live_context import LivePlacementContext

    from tests.support import execution_limits as test_limits
    from tests.support.limits import TEST_ONLY_AHEAD_LIMIT_MS, TEST_ONLY_BEHIND_LIMIT_MS

    live = case_input["live"]
    values: dict[str, Any] = {
        "signal": _build_signal(case_input),
        "plan_constraint_snapshot": _build_plan_snapshot(case_input),
        "execution_limits": test_limits.test_only_execution_limits(),
        "protection_registry": StubProtectionRegistry(),
        "latest_closed_bar_close": _coerce_decimal(
            live["latest_closed_bar_close"], "latest_closed_bar_close"
        ),
        "gtd_clock_margin": timedelta(
            milliseconds=max(TEST_ONLY_AHEAD_LIMIT_MS, TEST_ONLY_BEHIND_LIMIT_MS)
        ),
        "tp1_quantity_fraction": _coerce_decimal(
            live["tp1_quantity_fraction"], "tp1_quantity_fraction"
        ),
    }
    values.update(overrides)
    return LivePlacementContext(**values)


def _build_approved_plan(case_input: dict[str, Any]) -> Any:
    """Build a TradePlan from the fixture input."""
    from src.domain.enums import TradePlanStatus
    from src.domain.trade_plan import TradePlan

    return TradePlan(
        trade_plan_id=case_input["trade_plan_id"],
        signal_id=case_input["signal_id"],
        trade_plan_version=case_input["trade_plan_version"],
        entry_model=case_input["entry_model"],
        entry_min_price=_coerce_decimal(case_input["entry_min_price"], "entry_min_price"),
        entry_max_price=_coerce_decimal(case_input["entry_max_price"], "entry_max_price"),
        stop_loss_price=_coerce_decimal(case_input["stop_loss_price"], "stop_loss_price"),
        take_profit_json=case_input["take_profit_json"],
        invalidation_rule_json=case_input["invalidation_rule_json"],
        expiry_utc=_parse_utc(case_input["expiry_utc"]),
        expected_rr_json=case_input["expected_rr_json"],
        risk_rate=_coerce_decimal(case_input["risk_rate"], "risk_rate"),
        risk_budget=_coerce_decimal(case_input["risk_budget"], "risk_budget"),
        suggested_quantity=_coerce_decimal(case_input["suggested_quantity"], "suggested_quantity"),
        quantity_before_rounding=_coerce_decimal(
            case_input["quantity_before_rounding"], "quantity_before_rounding"
        ),
        quantity_after_rounding=_coerce_decimal(
            case_input["quantity_after_rounding"], "quantity_after_rounding"
        ),
        quantization_decision=case_input["quantization_decision"],
        plan_hash=_plan_hash_of(case_input),
        status=TradePlanStatus.APPROVED,
        created_at_utc=_parse_utc(case_input["created_at_utc"]),
    )


def _build_approval(case_input: dict[str, Any]) -> Any:
    """Build an APPROVED Approval from the fixture input."""
    from src.domain.approval import Approval
    from src.domain.enums import ApprovalAction, ApprovalResult

    return Approval(
        approval_id=case_input["approval_id"],
        trade_plan_id=case_input["trade_plan_id"],
        signal_id=case_input["signal_id"],
        action=ApprovalAction.APPROVE,
        result=ApprovalResult.APPROVED,
        status=ApprovalResult.APPROVED,
        approval_token_hash=case_input["token_hash"],
        requested_at_utc=_parse_utc(case_input["requested_at_utc"]),
        acted_at_utc=_parse_utc(case_input["acted_at_utc"]),
        actor_id=case_input.get("actor_id", ""),
        telegram_message_id=None,
        request_hash=_plan_hash_of(case_input),
    )


def _build_callback(case_input: dict[str, Any]) -> Any:
    """Build a Callback payload from the fixture input."""
    from src.approval.binding import Callback

    return Callback(
        raw_token=case_input["raw_token"],
        chat_id=case_input["chat_id"],
        plan_hash=_plan_hash_of(case_input),
        strategy_version=case_input["strategy_version"],
        parameter_set_id=case_input["parameter_set_id"],
        parameter_set_hash=case_input["parameter_set_hash"],
        callback_at_utc=_parse_utc(case_input["callback_at_utc"]),
    )


def _build_constraint_snapshot(case_input: dict[str, Any]) -> Any:
    """Build a ConstraintSnapshot from the fixture input."""
    from src.risk.types import ConstraintSnapshot

    return ConstraintSnapshot(
        symbol=case_input["symbol"],
        price_tick_size=_coerce_decimal(case_input["price_tick_size"], "price_tick_size"),
        quantity_step_size=_coerce_decimal(case_input["quantity_step_size"], "quantity_step_size"),
        min_quantity=_coerce_decimal(case_input["min_quantity"], "min_quantity"),
        min_notional=_coerce_decimal(case_input["min_notional"], "min_notional"),
        metadata_observed_at_utc=_parse_utc(case_input["metadata_observed_at_utc"]),
    )


def _build_account_state(case_input: dict[str, Any]) -> Any:
    """Build an AccountState from the fixture input."""
    from src.core.types import AccountState

    return AccountState(
        equity=_coerce_decimal(case_input["equity"], "equity"),
        risk_rate=_coerce_decimal(case_input["risk_rate"], "risk_rate"),
    )


def _build_open_positions(case_input: dict[str, Any]) -> list[Any]:
    """Build OpenPosition list from the fixture input."""
    from src.risk.types import OpenPosition

    return [
        OpenPosition(
            symbol=p["symbol"],
            position_side=p["position_side"],
            open_risk=_coerce_decimal(p["open_risk"], "open_risk"),
            daily_pnl_contribution=_coerce_decimal(
                p.get("daily_pnl_contribution", "0"), "daily_pnl_contribution"
            ),
        )
        for p in case_input.get("open_positions", [])
    ]


def _build_cost_rates(case_input: dict[str, Any]) -> Any:
    """Build the CostRates the live boundary requires from the fixture.

    The manager only serves live, so the fixture carries ACCOUNT_MAX rates
    (as `resolve_live_cost_rates` would return them).
    """
    from src.risk.cost_rates import CostRates

    raw = case_input["cost_rates"]
    provenance: dict[str, Any] = {}
    if raw["fee_source"] == "ACCOUNT_MAX":
        # Commission provenance as `resolve_live_cost_rates` stamps it: the
        # candidate symbol, observed one minute before `now_utc`, valid for
        # the fixture TTL (12-REVIEW WR-01).
        observed = _parse_utc(case_input["now_utc"]) - timedelta(seconds=60)
        ttl = timedelta(seconds=int(case_input["ttl_seconds"]))
        provenance = {
            "account_symbol": case_input["symbol"],
            "commission_observed_at_utc": observed,
            "commission_expires_at_utc": observed + ttl,
        }
    return CostRates(
        fee_rate_entry=_coerce_decimal(raw["fee_rate_entry"], "fee_rate_entry"),
        entry_slippage_rate=_coerce_decimal(raw["entry_slippage_rate"], "entry_slippage_rate"),
        fee_rate_exit=_coerce_decimal(raw["fee_rate_exit"], "fee_rate_exit"),
        exit_slippage_rate=_coerce_decimal(raw["exit_slippage_rate"], "exit_slippage_rate"),
        fee_source=raw["fee_source"],
        **provenance,
    )


def _build_risk_kwargs(case_input: dict[str, Any]) -> dict[str, Any]:
    """Build the kwargs for evaluate_risk from the fixture input."""
    # Convert string threshold values to Decimal (parameter_set expects
    # absolute quote amounts as Decimal, not strings).
    parameter_set: dict[str, Any] = {}
    for key, value in case_input["parameter_set"].items():
        if key == "max_open_positions":
            parameter_set[key] = int(value)
        else:
            parameter_set[key] = _coerce_decimal(value, key)

    return {
        "trade_plan": _build_approved_plan(case_input),
        "candidate_position_side": case_input["candidate_position_side"],
        "account_state": _build_account_state(case_input),
        "constraint_snapshot": _build_constraint_snapshot(case_input),
        "open_positions": _build_open_positions(case_input),
        "daily_loss_quote": _coerce_decimal(case_input["daily_loss_quote"], "daily_loss_quote"),
        "now_utc": _parse_utc(case_input["now_utc"]),
        "ttl": timedelta(seconds=int(case_input["ttl_seconds"])),
        "cost_rates": _build_cost_rates(case_input),
        "min_stop_distance_rate": _coerce_decimal(
            case_input["min_stop_distance_rate"], "min_stop_distance_rate"
        ),
        "max_cost_to_risk": _coerce_decimal(case_input["max_cost_to_risk"], "max_cost_to_risk"),
        "minimum_risk_utilization_after_rounding": _coerce_decimal(
            case_input["minimum_risk_utilization_after_rounding"],
            "minimum_risk_utilization_after_rounding",
        ),
        "parameter_set": parameter_set,
    }


# --------------------------------------------------------------------------- #
# Beh. 1 — happy path: approved plan + PASS risk → 1 entry + 1 SL call.
# --------------------------------------------------------------------------- #


async def test_happy_path_places_one_entry_and_one_sl_leg() -> None:
    """Beh. 1: an approved in-date plan with PASS risk verdict yields
    exactly one `place_entry` call (LIMIT, GTC, quantized qty,
    zone-derived limit price, x- EN id) followed by one
    `place_algo_protective` call (CONDITIONAL STOP_MARKET SL,
    close_position True, no quantity, xa- SL id).
    """
    from src.execution.manager import execute_approved_plan

    case_input = _load_input()
    expected = _load_expected()

    adapter = FakeExecutionAdapter()
    callback = _build_callback(case_input)
    approval = _build_approval(case_input)
    risk_kwargs = _build_risk_kwargs(case_input)

    outcome = await execute_approved_plan(
        callback=callback,
        approval=approval,
        authorized_chat_id=case_input["chat_id"],
        expiry_utc=_parse_utc(case_input["expiry_utc"]),
        approval_strategy_version=case_input["strategy_version"],
        approval_parameter_set_id=case_input["parameter_set_id"],
        approval_parameter_set_hash=case_input["parameter_set_hash"],
        now_utc=_parse_utc(case_input["now_utc"]),
        adapter=adapter,
        risk_kwargs=risk_kwargs,
        **_live_wiring(),
    )

    # Outcome is a PASS with the expected reason code.
    assert outcome.is_no_trade is False, f"expected PASS, got NO_TRADE: {outcome.reason_code}"
    assert outcome.reason_code == expected["outcome_reason_code"]

    # 1 entry + SL probe-by-id (CR-04/CR-05) + 1 SL placement.
    method_sequence = [c["method"] for c in adapter.calls]
    assert method_sequence == expected["method_sequence"], (
        f"adapter call sequence mismatch: got {method_sequence}, "
        f"expected {expected['method_sequence']}"
    )

    # Entry call: LIMIT, GTC, x- EN id, quantized qty, zone-mid price.
    entry_call = next(c for c in adapter.calls if c["method"] == "place_entry")
    entry_kwargs = entry_call["kwargs"]
    assert entry_kwargs["symbol"] == case_input["symbol"]
    assert entry_kwargs["side"] == case_input["side"]
    assert entry_kwargs["position_side"] == case_input["position_side"]
    assert entry_kwargs["time_in_force"] == "GTC"
    # Quantity comes from the risk verdict (sized.quantity), not the
    # fixture's quantity_after_rounding placeholder. The risk pipeline
    # computes the actual quantity from equity/risk_rate/SL distance.
    assert entry_kwargs["quantity"] > Decimal("0")
    # Hand-derived (plan 12-08): sizing entry 102, stop 98, cost
    # 102*0.0006 + 98*0.0008 = 0.1396, floor(10 / 4.1396) at step 0.001.
    assert entry_kwargs["quantity"] == Decimal("2.415")
    assert entry_kwargs["price"] == _coerce_decimal(
        case_input["expected_limit_price"], "expected_limit_price"
    )
    assert entry_kwargs["new_client_order_id"] == expected["entry_client_order_id"]

    # SL call: CONDITIONAL, STOP_MARKET, close_position True, xa- SL id.
    sl_call = next(c for c in adapter.calls if c["method"] == "place_algo_protective")
    assert sl_call["method"] == "place_algo_protective"
    sl_kwargs = sl_call["kwargs"]
    assert sl_kwargs["symbol"] == case_input["symbol"]
    assert sl_kwargs["side"] == case_input["sl_side"]
    assert sl_kwargs["algo_type"] == "CONDITIONAL"
    assert sl_kwargs["type"] == "STOP_MARKET"
    assert sl_kwargs["close_position"] is True
    assert sl_kwargs["quantity"] is None
    assert sl_kwargs["trigger_price"] == _coerce_decimal(
        case_input["stop_loss_price"], "stop_loss_price"
    )
    assert sl_kwargs["working_type"] == "MARK_PRICE"
    assert sl_kwargs["client_algo_id"] == expected["sl_algo_client_id"]


# --------------------------------------------------------------------------- #
# Beh. 2 — stale/expired plan yields no adapter calls.
# --------------------------------------------------------------------------- #


async def test_stale_plan_yields_no_adapter_calls_and_unapprovable_outcome() -> None:
    """Beh. 2: a stale/expired plan yields no adapter calls and an
    UNAPPROVABLE outcome with reason code APPROVAL_EXPIRED.
    """
    from src.execution.manager import execute_approved_plan

    case_input = _load_input()
    adapter = FakeExecutionAdapter()
    callback = _build_callback(case_input)
    approval = _build_approval(case_input)
    risk_kwargs = _build_risk_kwargs(case_input)

    # now_utc is past expiry_utc → APPROVAL_EXPIRED.
    past_now = _parse_utc(case_input["expiry_utc"]) + timedelta(seconds=1)
    risk_kwargs["now_utc"] = past_now  # one clock (09-REVIEW WR-05)

    outcome = await execute_approved_plan(
        callback=callback,
        approval=approval,
        authorized_chat_id=case_input["chat_id"],
        expiry_utc=_parse_utc(case_input["expiry_utc"]),
        approval_strategy_version=case_input["strategy_version"],
        approval_parameter_set_id=case_input["parameter_set_id"],
        approval_parameter_set_hash=case_input["parameter_set_hash"],
        now_utc=past_now,
        adapter=adapter,
        risk_kwargs=risk_kwargs,
        **_live_wiring(),
    )

    # Outcome is NO_TRADE with APPROVAL_EXPIRED.
    assert outcome.is_no_trade is True
    assert outcome.reason_code == "APPROVAL_EXPIRED"

    # Zero adapter calls.
    assert adapter.calls == [], (
        f"stale plan must not trigger any adapter calls, got {adapter.calls}"
    )


# --------------------------------------------------------------------------- #
# Beh. 3 — risk NO_TRADE verdict yields no adapter calls.
# --------------------------------------------------------------------------- #


async def test_risk_no_trade_yields_no_adapter_calls_and_preserves_reason_code() -> None:
    """Beh. 3: a risk NO_TRADE verdict yields no adapter calls and the
    risk reason code is preserved byte-identically.
    """
    from src.execution.manager import execute_approved_plan

    case_input = _load_input()
    adapter = FakeExecutionAdapter()
    callback = _build_callback(case_input)
    approval = _build_approval(case_input)
    risk_kwargs = _build_risk_kwargs(case_input)

    # Force a risk NO_TRADE by setting equity to a value that makes
    # sizing fail (zero SL distance is not possible here, so we use a
    # very small equity that makes allowed_risk < risk_per_unit).
    risk_kwargs["account_state"] = type(risk_kwargs["account_state"])(
        equity=Decimal("0.01"),
        risk_rate=risk_kwargs["account_state"].risk_rate,
    )

    outcome = await execute_approved_plan(
        callback=callback,
        approval=approval,
        authorized_chat_id=case_input["chat_id"],
        expiry_utc=_parse_utc(case_input["expiry_utc"]),
        approval_strategy_version=case_input["strategy_version"],
        approval_parameter_set_id=case_input["parameter_set_id"],
        approval_parameter_set_hash=case_input["parameter_set_hash"],
        now_utc=_parse_utc(case_input["now_utc"]),
        adapter=adapter,
        risk_kwargs=risk_kwargs,
        **_live_wiring(),
    )

    # Outcome is NO_TRADE with a risk reason code (not APPROVAL_EXPIRED).
    assert outcome.is_no_trade is True
    assert outcome.reason_code != "APPROVAL_EXPIRED"
    assert outcome.reason_code != "OK"

    # Zero adapter calls.
    assert adapter.calls == [], (
        f"risk NO_TRADE must not trigger any adapter calls, got {adapter.calls}"
    )


# --------------------------------------------------------------------------- #
# Beh. 4 — ambiguous place_entry response triggers query_order_by_client first.
# --------------------------------------------------------------------------- #


async def test_ambiguous_entry_response_triggers_query_before_retry() -> None:
    """Beh. 4: an ambiguous `place_entry` response triggers
    `query_order_by_client` first; retry occurs only when the probe
    confirms absence.
    """
    from src.execution.manager import execute_approved_plan

    case_input = _load_input()
    adapter = FakeExecutionAdapter()
    callback = _build_callback(case_input)
    approval = _build_approval(case_input)
    risk_kwargs = _build_risk_kwargs(case_input)

    # Simulate an ambiguous placement the way the REAL adapter surfaces it
    # (it raises; it never returns None), and a probe returning the REAL
    # `OrderProbe` dataclass (attribute access, not dict `.get`).
    from src.adapters.binance_usdm import OrderProbe

    adapter.entry_exceptions.append(TimeoutError("read timeout — status unknown"))
    adapter._query_response = OrderProbe(  # type: ignore[attr-defined]
        client_order_id=_load_expected()["entry_client_order_id"],
        found=True,
        order_id="12345",
        status="NEW",
        update_time_utc=None,
    )

    await execute_approved_plan(
        callback=callback,
        approval=approval,
        authorized_chat_id=case_input["chat_id"],
        expiry_utc=_parse_utc(case_input["expiry_utc"]),
        approval_strategy_version=case_input["strategy_version"],
        approval_parameter_set_id=case_input["parameter_set_id"],
        approval_parameter_set_hash=case_input["parameter_set_hash"],
        now_utc=_parse_utc(case_input["now_utc"]),
        adapter=adapter,
        risk_kwargs=risk_kwargs,
        **_live_wiring(),
    )

    # The manager should have called query_order_by_client before any
    # retry. Since the probe found the order, no retry is needed.
    method_sequence = [c["method"] for c in adapter.calls]
    assert "query_order_by_client" in method_sequence, (
        f"ambiguous response must trigger query_order_by_client, got {method_sequence}"
    )
    # Query must come after the initial place_entry.
    entry_idx = method_sequence.index("place_entry")
    query_idx = method_sequence.index("query_order_by_client")
    assert query_idx > entry_idx, f"query must come after initial place_entry: {method_sequence}"
    # No retry place_entry after the query (probe found the order).
    entry_count = method_sequence.count("place_entry")
    assert entry_count == 1, f"probe found order → no retry, got {entry_count} place_entry calls"


# --------------------------------------------------------------------------- #
# 09-REVIEW CR-09 — no blind retry; probe outcome decides; unknown fails closed.
# --------------------------------------------------------------------------- #


class _ExchangeStateBlind:
    """Adapter proxy whose open-order snapshots answer "no orders" (plan 19-13).

    The negative controls run the manager against a store that never remembers
    (`AlwaysWinsIntentStore`) to prove that the DURABLE ROW, not the exchange, is the
    exactly-once guard (F-126, F-951). The manager now also refuses a symbol with an open order
    (gate 5e), which would stop the second delivery before it reaches the exchange and make
    those controls vacuous. For them only, the snapshot reads are blinded; every other call is
    delegated unchanged, so the wrapped fake still records the placements.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def snapshot_open_normal_orders(self, **kwargs: Any) -> list[Any]:
        return []

    async def snapshot_open_algo_orders(self, **kwargs: Any) -> list[Any]:
        return []


def _prime_mark_price(adapter: Any, case_input: dict[str, Any]) -> None:
    """Give a stateful exchange fake a fresh mark price when its test set none (plan 19-13).

    `BinanceSemanticsFakeAdapter` raises for a symbol with no mark price, by design. The
    execution manager now reads the mark price before it places, so the PG and recovery
    suites that run the manager against that fake get the fixture price here, aged by the
    fixture's `mark_age_ms`. A fake without `set_mark_price` (this module's own) is untouched.
    """
    set_price = getattr(adapter, "set_mark_price", None)
    known = getattr(adapter, "_mark_prices", None)
    if set_price is None or not isinstance(known, dict) or case_input["symbol"] in known:
        return
    reading = _mark_reading_for(case_input)
    set_price(case_input["symbol"], reading.mark_price, reading.exchange_time_utc)


async def _run_plan(
    adapter: FakeExecutionAdapter, *, case_input: dict[str, Any] | None = None, **overrides: Any
) -> Any:
    """Run `execute_approved_plan` on the golden fixture (or an edited copy) with overrides."""
    from src.execution.manager import execute_approved_plan

    case = case_input if case_input is not None else _load_input()
    _prime_mark_price(adapter, case)
    kwargs: dict[str, Any] = {
        "callback": _build_callback(case),
        "approval": _build_approval(case),
        "authorized_chat_id": case["chat_id"],
        "expiry_utc": _parse_utc(case["expiry_utc"]),
        "approval_strategy_version": case["strategy_version"],
        "approval_parameter_set_id": case["parameter_set_id"],
        "approval_parameter_set_hash": case["parameter_set_hash"],
        "now_utc": _parse_utc(case["now_utc"]),
        "adapter": adapter,
        "risk_kwargs": _build_risk_kwargs(case),
        **_live_wiring(case_input=case),
    }
    kwargs.update(overrides)
    if isinstance(kwargs["intent_store"], AlwaysWinsIntentStore):
        kwargs["adapter"] = _ExchangeStateBlind(kwargs["adapter"])
    return await execute_approved_plan(**kwargs)


def _probe(found: bool) -> Any:
    from src.adapters.binance_usdm import OrderProbe

    return OrderProbe(
        client_order_id=_load_expected()["entry_client_order_id"],
        found=found,
        order_id="12345" if found else None,
        status="NEW" if found else None,
        update_time_utc=None,
    )


async def test_definitive_absence_allows_exactly_one_retry() -> None:
    """CR-09: an ambiguous entry followed by a DEFINITIVE `found=False`
    probe retries once; the retry's ack proceeds to the SL."""
    adapter = FakeExecutionAdapter()
    adapter.entry_exceptions.append(TimeoutError("status unknown"))
    adapter.query_responses.append(_probe(found=False))

    outcome = await _run_plan(adapter)

    assert outcome.is_no_trade is False
    assert [c["method"] for c in adapter.calls] == [
        *PRE_PLACEMENT_READS,
        "get_position_mode",
        "place_entry",
        "query_order_by_client",
        "place_entry",
        "query_algo_order_by_client",
        "place_algo_protective",
    ]


async def test_probe_failure_fails_closed_to_safe_mode_without_retry_or_sl() -> None:
    """CR-09: a probe that raises (unknown existence) must NOT be treated
    as absence — no retry, no SL, SAFE_MODE, RECONCILIATION_REQUIRED."""
    adapter = FakeExecutionAdapter()
    adapter.entry_exceptions.append(TimeoutError("status unknown"))
    adapter.query_exceptions.append(RuntimeError("-2013 Order does not exist"))
    safe_mode_controller = RecordingSafeModeController()

    outcome = await _run_plan(adapter, safe_mode_controller=safe_mode_controller)

    assert outcome.is_no_trade is True
    assert outcome.reason_code == "RECONCILIATION_REQUIRED"
    assert [c["method"] for c in adapter.calls] == [
        *PRE_PLACEMENT_READS,
        "get_position_mode",
        "place_entry",
        "query_order_by_client",
    ]
    assert safe_mode_controller.entered_reasons == ["ENTRY_STATE_UNKNOWN"]


async def test_indeterminate_probe_is_unknown_not_absent() -> None:
    """CR-09: a `None` probe is unknown (fail closed), never 'absent'."""
    adapter = FakeExecutionAdapter()
    adapter.entry_exceptions.append(TimeoutError("status unknown"))
    safe_mode_controller = RecordingSafeModeController()

    outcome = await _run_plan(adapter, safe_mode_controller=safe_mode_controller)

    assert outcome.reason_code == "RECONCILIATION_REQUIRED"
    assert [c["method"] for c in adapter.calls].count("place_entry") == 1
    assert safe_mode_controller.entered_reasons == ["ENTRY_STATE_UNKNOWN"]


async def test_repeated_definitive_absence_is_bounded_no_trade() -> None:
    """CR-09: at most two entry attempts; both absent → NO_TRADE, no SL."""
    adapter = FakeExecutionAdapter()
    adapter.entry_exceptions.extend([RuntimeError("-2019"), RuntimeError("-2019")])
    adapter.query_responses.extend([_probe(found=False), _probe(found=False)])
    safe_mode_controller = RecordingSafeModeController()

    outcome = await _run_plan(adapter, safe_mode_controller=safe_mode_controller)

    assert outcome.is_no_trade is True
    assert outcome.reason_code == "EXCHANGE_CONSTRAINT"
    methods = [c["method"] for c in adapter.calls]
    assert methods.count("place_entry") == 2
    assert "place_algo_protective" not in methods
    assert safe_mode_controller.entered_reasons == []


async def test_real_adapter_place_entry_makes_a_single_attempt() -> None:
    """CR-09: the adapter never retries placement itself — a transient
    failure surfaces after exactly one SDK call."""
    from types import SimpleNamespace

    import pytest
    from src.adapters.binance_usdm import BinanceUsdmAdapter

    class _Rest:
        def __init__(self) -> None:
            self.calls = 0

        def new_order(self, **kwargs: Any) -> Any:
            self.calls += 1
            raise TimeoutError("read timeout")

    rest = _Rest()
    # Plan 18-13: a signed call needs the TEST_ONLY policy and the one shared gate.
    from datetime import UTC, datetime

    from src.adapters.binance_ratelimit_gate import RestRateLimitGate

    from tests.support.limits import test_only_signed_call_policy

    policy = test_only_signed_call_policy()
    adapter = BinanceUsdmAdapter(
        sdk_client=SimpleNamespace(rest_api=rest),  # type: ignore[arg-type]
        signed_call_policy=policy,
        rest_gate=RestRateLimitGate(
            policy=policy.rate_limit, clock=lambda: datetime(2026, 10, 16, tzinfo=UTC)
        ),
    )
    with pytest.raises(TimeoutError):
        await adapter.place_entry(
            symbol="BTCUSDT",
            side="BUY",
            position_side="BOTH",
            time_in_force="GTC",
            quantity=Decimal("0.100"),
            price=Decimal("101.00"),
            new_client_order_id="x-33333333333333333333333333333333EN",
        )
    assert rest.calls == 1


# --------------------------------------------------------------------------- #
# Beh. 5 — golden fixture: byte-exact adapter call sequence.
# --------------------------------------------------------------------------- #


async def test_golden_fixture_adapter_call_sequence_matches_expected() -> None:
    """Beh. 5: the golden fixture's expected adapter call sequence
    matches the actual recorded sequence byte-for-byte.
    """
    from src.execution.manager import execute_approved_plan

    case_input = _load_input()
    expected = _load_expected()

    adapter = FakeExecutionAdapter()
    callback = _build_callback(case_input)
    approval = _build_approval(case_input)
    risk_kwargs = _build_risk_kwargs(case_input)

    await execute_approved_plan(
        callback=callback,
        approval=approval,
        authorized_chat_id=case_input["chat_id"],
        expiry_utc=_parse_utc(case_input["expiry_utc"]),
        approval_strategy_version=case_input["strategy_version"],
        approval_parameter_set_id=case_input["parameter_set_id"],
        approval_parameter_set_hash=case_input["parameter_set_hash"],
        now_utc=_parse_utc(case_input["now_utc"]),
        adapter=adapter,
        risk_kwargs=risk_kwargs,
        **_live_wiring(),
    )

    # Method sequence matches.
    method_sequence = [c["method"] for c in adapter.calls]
    assert method_sequence == expected["method_sequence"]

    # Entry client_order_id matches the deterministic derivation.
    entry_call = next(c for c in adapter.calls if c["method"] == "place_entry")
    assert entry_call["kwargs"]["new_client_order_id"] == expected["entry_client_order_id"]

    # SL algo_client_id matches the deterministic derivation.
    sl_call = next(c for c in adapter.calls if c["method"] == "place_algo_protective")
    assert sl_call["kwargs"]["client_algo_id"] == expected["sl_algo_client_id"]


def test_execute_approved_plan_is_a_coroutine_function() -> None:
    """09-REVIEW CR-06: the manager is awaited on the caller's running
    loop (PTB / FastAPI); it must never call `asyncio.run` itself."""
    import inspect

    from src.execution import manager

    assert inspect.iscoroutinefunction(manager.execute_approved_plan)
    source = (Path(__file__).parents[1] / "src" / "execution" / "manager.py").read_text(
        encoding="utf-8"
    )
    assert "asyncio.run(" not in source


# --------------------------------------------------------------------------- #
# Beh. 6 — purity: no Binance SDK imports in execution core.
# --------------------------------------------------------------------------- #


def test_execution_core_does_not_import_binance_sdk() -> None:
    """Beh. 6: src/execution/manager.py and src/execution/placement.py
    do not import the Binance SDK. Only the adapter imports it.
    """
    import re
    from pathlib import Path

    for module_path in (
        Path(__file__).resolve().parents[1] / "src" / "execution" / "manager.py",
        Path(__file__).resolve().parents[1] / "src" / "execution" / "placement.py",
    ):
        source = module_path.read_text(encoding="utf-8")
        forbidden_patterns = [
            r"\bimport\s+binance_sdk\b",
            r"\bfrom\s+binance_sdk\b",
        ]
        for pattern in forbidden_patterns:
            match = re.search(pattern, source)
            assert match is None, (
                f"forbidden import in {module_path}: pattern={pattern!r}, match={match.group(0)!r}"
            )


# --------------------------------------------------------------------------- #
# Beh. 7 — purity: no float() in execution core placement math.
# --------------------------------------------------------------------------- #


def test_execution_core_has_no_float_in_placement_math() -> None:
    """Beh. 7: src/execution/manager.py and src/execution/placement.py
    do not use float() for placement math. Decimal-only per D-05.
    """
    import re
    from pathlib import Path

    for module_path in (
        Path(__file__).resolve().parents[1] / "src" / "execution" / "manager.py",
        Path(__file__).resolve().parents[1] / "src" / "execution" / "placement.py",
    ):
        source = module_path.read_text(encoding="utf-8")
        # float() is only allowed at the adapter boundary, not in core.
        match = re.search(r"\bfloat\s*\(", source)
        assert match is None, f"float() found in {module_path}: {match.group(0)!r}"


# --------------------------------------------------------------------------- #
# 09-REVIEW CR-05 — the entry-time SL result is checked; failure fails closed.
# --------------------------------------------------------------------------- #


async def test_rejected_sl_cancels_entry_and_forces_safe_mode() -> None:
    """CR-05: an acknowledged entry whose SL is REJECTED is not OK — the
    entry is canceled by its deterministic id (journal-first), SAFE_MODE
    is entered, and the outcome is ENTRY_WITHOUT_PROTECTIVE."""
    adapter = FakeExecutionAdapter(algo_response={"algo_status": "REJECTED"})
    safe_mode_controller = RecordingSafeModeController()
    journal = FakeJournal()

    outcome = await _run_plan(adapter, safe_mode_controller=safe_mode_controller, journal=journal)

    assert outcome.is_no_trade is True
    assert outcome.reason_code == "ENTRY_WITHOUT_PROTECTIVE"
    assert safe_mode_controller.entered_reasons == ["ENTRY_WITHOUT_PROTECTIVE"]
    cancel_calls = [c for c in adapter.calls if c["method"] == "cancel_normal_order"]
    assert cancel_calls == [
        {
            "method": "cancel_normal_order",
            "kwargs": {
                "symbol": "BTCUSDT",
                "orig_client_order_id": _load_expected()["entry_client_order_id"],
            },
        }
    ]
    phases = [json.loads(e.payload_json)["phase"] for e in journal.events]
    assert phases == ["pre_cancel", "post_cancel"]


async def test_raising_sl_after_entry_ack_fails_closed() -> None:
    """CR-05: an SL placement EXCEPTION after the entry was acknowledged
    never escapes with a resting, unprotected entry on the book."""

    class _SlRaises(FakeExecutionAdapter):
        async def place_algo_protective(self, **kwargs: Any) -> Any:
            await super().place_algo_protective(**kwargs)
            raise TimeoutError("SL placement timeout")

    adapter = _SlRaises()
    safe_mode_controller = RecordingSafeModeController()

    outcome = await _run_plan(adapter, safe_mode_controller=safe_mode_controller)

    assert outcome.reason_code == "ENTRY_WITHOUT_PROTECTIVE"
    assert safe_mode_controller.entered_reasons == ["ENTRY_WITHOUT_PROTECTIVE"]
    assert [c["method"] for c in adapter.calls][-1] == "cancel_normal_order"


# --------------------------------------------------------------------------- #
# 09-REVIEW CR-07 — enablement, SAFE_MODE and placement gates are mandatory.
# --------------------------------------------------------------------------- #


async def test_disabled_live_orders_block_placement() -> None:
    """CR-07: a default (disabled) controller blocks before any order."""
    from src.execution.enablement import LiveEnablementController

    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(adapter, enablement=LiveEnablementController(journal=FakeJournal()))
    assert outcome.is_no_trade is True
    assert outcome.reason_code == "DISABLED"
    assert adapter.calls == []


async def test_safe_mode_blocks_new_entries_even_when_enabled() -> None:
    """CR-07: SAFE_MODE (e.g. after ENTRY_WITHOUT_PROTECTIVE) blocks the
    next approved plan even though live orders are still enabled."""
    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(
        adapter, safe_mode_controller=RecordingSafeModeController(in_safe_mode=True)
    )
    assert outcome.is_no_trade is True
    assert outcome.reason_code == "RECONCILIATION_REQUIRED"
    assert adapter.calls == []


async def test_real_safe_mode_controller_blocks_after_entering_safe_mode() -> None:
    """CR-07: the real `SafeModeController.guard_new_entries` is consulted."""
    from src.reconcile.safe_mode import SafeModeController

    class _NoOpTruth:
        async def snapshot_open_normal_orders(self, *, symbol: Any = None) -> list[Any]:
            return []

        async def snapshot_open_algo_orders(self, *, symbol: Any = None) -> list[Any]:
            return []

        async def snapshot_positions(self, *, symbol: Any = None) -> list[Any]:
            return []

    controller = SafeModeController(adapter=_NoOpTruth(), journal=FakeJournal())
    controller.enter_safe_mode(
        reason="ENTRY_WITHOUT_PROTECTIVE", now_utc=datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
    )
    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(adapter, safe_mode_controller=controller)
    assert outcome.reason_code == "RECONCILIATION_REQUIRED"
    assert adapter.calls == []


async def test_unreconciled_positions_block_placement() -> None:
    """CR-07: reconciliation is always checked (gates are mandatory)."""
    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(
        adapter,
        gate_kwargs=_build_gate_kwargs(_load_input(), positions_reconciled=False),
    )
    assert outcome.is_no_trade is True
    assert outcome.reason_code == "UNCERTAIN_ACCOUNT_STATE"
    assert adapter.calls == []


async def test_missing_live_gates_raise_before_any_adapter_call() -> None:
    """CR-07: `None` enablement / gate inputs are programming errors."""
    import pytest

    for override in ({"enablement": None}, {"gate_kwargs": None}):
        adapter = FakeExecutionAdapter()
        with pytest.raises(ValueError, match="is required"):
            await _run_plan(adapter, **override)
        assert adapter.calls == []


# --------------------------------------------------------------------------- #
# 09-REVIEW CR-08 — the approval must be an APPROVE for THIS plan.
# --------------------------------------------------------------------------- #


async def test_skip_approval_row_with_valid_token_never_places() -> None:
    """CR-08: a SKIP/SKIPPED approval row that binds OK is not an
    authorization to trade."""
    import dataclasses

    from src.domain.enums import ApprovalAction, ApprovalResult

    approval = dataclasses.replace(
        _build_approval(_load_input()),
        action=ApprovalAction.SKIP_USER,
        result=ApprovalResult.SKIPPED,
        status=ApprovalResult.SKIPPED,
    )
    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(adapter, approval=approval)
    assert outcome.is_no_trade is True
    assert outcome.reason_code == "INVALIDATED"
    assert adapter.calls == []


async def test_pending_approval_never_places() -> None:
    """CR-08: an APPROVE row that has not resolved to APPROVED is rejected."""
    import dataclasses

    from src.domain.enums import ApprovalResult

    approval = dataclasses.replace(
        _build_approval(_load_input()),
        result=ApprovalResult.PENDING,
        status=ApprovalResult.PENDING,
        acted_at_utc=None,
    )
    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(adapter, approval=approval)
    assert outcome.reason_code == "INVALIDATED"
    assert adapter.calls == []


async def test_skip_button_callback_never_places() -> None:
    """CR-08: the pressed button (callback.action) must be APPROVE."""
    import dataclasses

    from src.domain.enums import ApprovalAction

    callback = dataclasses.replace(_build_callback(_load_input()), action=ApprovalAction.SKIP_BUSY)
    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(adapter, callback=callback)
    assert outcome.reason_code == "INVALIDATED"
    assert adapter.calls == []


async def test_executed_plan_must_be_the_approved_plan() -> None:
    """CR-08: a different plan (hash or id) under a valid approval is
    STALE_SETUP — its hash would otherwise mint the order ids."""
    import dataclasses

    case_input = _load_input()
    for field, value in (
        ("plan_hash", "4" * 64),
        ("trade_plan_id", "tp_some_other_plan"),
    ):
        risk_kwargs = _build_risk_kwargs(case_input)
        risk_kwargs["trade_plan"] = dataclasses.replace(risk_kwargs["trade_plan"], **{field: value})
        adapter = FakeExecutionAdapter()
        outcome = await _run_plan(adapter, risk_kwargs=risk_kwargs)
        assert outcome.reason_code == "STALE_SETUP", field
        assert adapter.calls == [], field


async def test_fresher_caller_expiry_cannot_revive_a_stale_plan() -> None:
    """CR-08: the binding's expiry must be the plan's own expiry_utc."""
    from datetime import timedelta

    case_input = _load_input()
    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(
        adapter, expiry_utc=_parse_utc(case_input["expiry_utc"]) + timedelta(hours=6)
    )
    assert outcome.reason_code == "STALE_SETUP"
    assert adapter.calls == []


# --------------------------------------------------------------------------- #
# 09-REVIEW WR-01 — limit prices are snapped onto the tick grid.
# --------------------------------------------------------------------------- #


async def test_odd_tick_zone_mid_is_floored_for_a_buy_limit() -> None:
    """WR-01: (100.01 + 100.02) / 2 = 100.015 is off-grid; a BUY limit
    floors to 100.01 (never pays up)."""
    # The zone is a hashed field: the edited case re-derives its plan hash (plan 19-13).
    case_input = {
        **_load_input(),
        "entry_min_price": "100.01",
        "entry_max_price": "100.02",
        "quantity_after_rounding": "100",
    }
    adapter = FakeExecutionAdapter(case_input=case_input)
    adapter.mark_reading = _mark_reading_for(case_input, mark_price=Decimal("100.015"))

    outcome = await _run_plan(adapter, case_input=case_input)

    assert outcome.is_no_trade is False, outcome
    entry_call = next(c for c in adapter.calls if c["method"] == "place_entry")
    assert entry_call["kwargs"]["price"] == Decimal("100.01")


# --------------------------------------------------------------------------- #
# 09-REVIEW WR-02 — position mode is detected at placement time.
# --------------------------------------------------------------------------- #


async def test_hedge_mode_is_refused_before_any_order() -> None:
    """D-14 (was WR-02): a Hedge account is unsupported in V1 and refused before the approval is
    consumed. The hedge payload matrix stays proven offline in tests/test_execution_modes.py."""
    case_input = _load_input()
    adapter = FakeExecutionAdapter(position_mode="HEDGE")
    store = InMemoryExecutionIntentStore()

    outcome = await _run_plan(adapter, intent_store=store)

    assert (outcome.is_no_trade, outcome.reason_code) == (True, "HEDGE_MODE_UNSUPPORTED")
    methods = [c["method"] for c in adapter.calls]
    assert methods == [*PRE_PLACEMENT_READS, "get_position_mode"]
    assert "place_entry" not in methods
    assert "place_algo_protective" not in methods
    assert store.get_entry(approval_id=case_input["approval_id"]) is None


async def test_undeterminable_position_mode_fails_closed_before_any_order() -> None:
    """WR-02: an account-mode query failure never defaults to BOTH."""
    adapter = FakeExecutionAdapter(position_mode="UNKNOWN")
    outcome = await _run_plan(adapter)

    assert outcome.is_no_trade is True
    assert outcome.reason_code == "UNCERTAIN_ACCOUNT_STATE"
    assert [c["method"] for c in adapter.calls] == [*PRE_PLACEMENT_READS, "get_position_mode"]


def test_resolve_position_mode_maps_only_real_bools() -> None:
    import pytest
    from src.adapters.binance_usdm import PositionModeResult
    from src.execution.manager import resolve_position_mode

    assert resolve_position_mode(PositionModeResult(dual_side_position=True)) == "HEDGE"
    assert resolve_position_mode(PositionModeResult(dual_side_position=False)) == "ONE_WAY"
    for bad in ("ONE_WAY", None, {"dual_side_position": "true"}):
        with pytest.raises(ValueError):
            resolve_position_mode(bad)


# --------------------------------------------------------------------------- #
# 09-REVIEW WR-05 — gates judge exactly what is placed, on one clock.
# --------------------------------------------------------------------------- #


async def test_headroom_gate_uses_the_managers_inputs() -> None:
    """WR-05: headroom exhaustion rejects before any order."""
    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(
        adapter, gate_kwargs=_build_gate_kwargs(_load_input(), open_algo_count=196)
    )
    assert outcome.reason_code == "EXCHANGE_CONSTRAINT"
    assert adapter.calls == []


async def test_caller_cannot_inject_a_foreign_sized_result_or_snapshot() -> None:
    """WR-05: `sized` / `constraint_snapshot` / `now_utc` are derived,
    never caller-supplied gate inputs."""
    import pytest

    adapter = FakeExecutionAdapter()
    with pytest.raises(ValueError, match="gate_kwargs keys"):
        await _run_plan(adapter, gate_kwargs=_build_gate_kwargs(_load_input(), sized=object()))
    assert adapter.calls == []


async def test_mismatched_risk_clock_raises() -> None:
    """WR-05: risk and gates must run on the manager's single now_utc."""
    from datetime import timedelta

    import pytest

    case_input = _load_input()
    risk_kwargs = _build_risk_kwargs(case_input)
    risk_kwargs["now_utc"] = risk_kwargs["now_utc"] - timedelta(minutes=5)
    adapter = FakeExecutionAdapter()
    with pytest.raises(ValueError, match="now_utc"):
        await _run_plan(adapter, risk_kwargs=risk_kwargs)
    assert adapter.calls == []


# --------------------------------------------------------------------------- #
# Phase 12 (D-11, D-12) — only account-sourced rates may size a real order.
# --------------------------------------------------------------------------- #


async def test_parameter_fee_source_is_no_trade_before_risk_and_adapter(
    monkeypatch: Any,
) -> None:
    """D-11/D-12: parameter fees never size a live order. The rate gate
    returns UNCERTAIN_ACCOUNT_STATE before `evaluate_risk` runs, with zero
    adapter calls (T-12-23)."""
    import src.execution.manager as manager
    from src.risk.cost_rates import FEE_SOURCE_PARAMETER, CostRates

    def _must_not_run(**_kwargs: Any) -> Any:
        raise AssertionError("evaluate_risk must not run for a PARAMETER fee source")

    monkeypatch.setattr(manager, "evaluate_risk", _must_not_run)

    risk_kwargs = _build_risk_kwargs(_load_input())
    account_rates = risk_kwargs["cost_rates"]
    risk_kwargs["cost_rates"] = CostRates(
        fee_rate_entry=account_rates.fee_rate_entry,
        entry_slippage_rate=account_rates.entry_slippage_rate,
        fee_rate_exit=account_rates.fee_rate_exit,
        exit_slippage_rate=account_rates.exit_slippage_rate,
        fee_source=FEE_SOURCE_PARAMETER,
    )
    adapter = FakeExecutionAdapter()

    outcome = await _run_plan(adapter, risk_kwargs=risk_kwargs)

    assert outcome.is_no_trade is True
    assert outcome.reason_code == "UNCERTAIN_ACCOUNT_STATE"
    assert adapter.calls == []


async def test_account_max_rates_for_another_symbol_are_no_trade(monkeypatch: Any) -> None:
    """12-REVIEW WR-01: ACCOUNT_MAX rates resolved from another symbol's
    commission never size this order; NO_TRADE before risk and adapter."""
    from dataclasses import replace

    import src.execution.manager as manager

    def _must_not_run(**_kwargs: Any) -> Any:
        raise AssertionError("evaluate_risk must not run for a foreign commission")

    monkeypatch.setattr(manager, "evaluate_risk", _must_not_run)
    risk_kwargs = _build_risk_kwargs(_load_input())
    risk_kwargs["cost_rates"] = replace(risk_kwargs["cost_rates"], account_symbol="ETHUSDT")
    adapter = FakeExecutionAdapter()

    outcome = await _run_plan(adapter, risk_kwargs=risk_kwargs)

    assert outcome.is_no_trade is True
    assert outcome.reason_code == "UNCERTAIN_ACCOUNT_STATE"
    assert adapter.calls == []


async def test_account_max_rates_expired_at_placement_are_no_trade(monkeypatch: Any) -> None:
    """12-REVIEW WR-01: a commission that expired between resolution and
    placement is re-checked against the manager's own clock."""
    from dataclasses import replace

    import src.execution.manager as manager

    def _must_not_run(**_kwargs: Any) -> Any:
        raise AssertionError("evaluate_risk must not run for a stale commission")

    monkeypatch.setattr(manager, "evaluate_risk", _must_not_run)
    risk_kwargs = _build_risk_kwargs(_load_input())
    risk_kwargs["cost_rates"] = replace(
        risk_kwargs["cost_rates"],
        commission_expires_at_utc=risk_kwargs["now_utc"] - timedelta(seconds=1),
    )
    adapter = FakeExecutionAdapter()

    outcome = await _run_plan(adapter, risk_kwargs=risk_kwargs)

    assert outcome.is_no_trade is True
    assert outcome.reason_code == "UNCERTAIN_ACCOUNT_STATE"
    assert adapter.calls == []


def test_account_max_label_without_provenance_cannot_be_constructed() -> None:
    """12-REVIEW WR-01: the ACCOUNT_MAX label alone is not constructible."""
    import pytest
    from src.risk.cost_rates import FEE_SOURCE_ACCOUNT_MAX, CostRates

    with pytest.raises(ValueError, match="ACCOUNT_MAX"):
        CostRates(
            fee_rate_entry=Decimal("0.0004"),
            entry_slippage_rate=Decimal("0.0002"),
            fee_rate_exit=Decimal("0.0004"),
            exit_slippage_rate=Decimal("0.0002"),
            fee_source=FEE_SOURCE_ACCOUNT_MAX,
        )


async def test_missing_or_wrong_typed_cost_rates_raises_type_error() -> None:
    """A missing `cost_rates` key or a non-`CostRates` value (a plain dict)
    raises TypeError before any adapter call."""
    import pytest

    missing = _build_risk_kwargs(_load_input())
    del missing["cost_rates"]
    adapter = FakeExecutionAdapter()
    with pytest.raises(TypeError, match="cost_rates"):
        await _run_plan(adapter, risk_kwargs=missing)
    assert adapter.calls == []

    wrong_type = _build_risk_kwargs(_load_input())
    wrong_type["cost_rates"] = dict(_load_input()["cost_rates"])
    adapter = FakeExecutionAdapter()
    with pytest.raises(TypeError, match="resolve_live_cost_rates"):
        await _run_plan(adapter, risk_kwargs=wrong_type)
    assert adapter.calls == []


async def test_legacy_modeled_costs_per_unit_keyword_raises_type_error() -> None:
    """The removed `modeled_costs_per_unit` keyword is rejected before any
    adapter call, even beside valid account-sourced rates."""
    import pytest

    risk_kwargs = _build_risk_kwargs(_load_input())
    risk_kwargs["modeled_costs_per_unit"] = Decimal("0.02")
    adapter = FakeExecutionAdapter()
    with pytest.raises(TypeError, match="modeled_costs_per_unit"):
        await _run_plan(adapter, risk_kwargs=risk_kwargs)
    assert adapter.calls == []


# --------------------------------------------------------------------------- #
# Phase 17 plan 11 — identity-before-replay, SL write-ahead, fail-closed store
# handling (D-14, D-15, D-16, F-703, F-951).
# --------------------------------------------------------------------------- #


def _binding_args(**overrides: Any) -> dict[str, Any]:
    case_input = _load_input()
    args: dict[str, Any] = {
        "callback": _build_callback(case_input),
        "approval": _build_approval(case_input),
        "authorized_chat_id": case_input["chat_id"],
        "approval_strategy_version": case_input["strategy_version"],
        "approval_parameter_set_id": case_input["parameter_set_id"],
        "approval_parameter_set_hash": case_input["parameter_set_hash"],
    }
    args.update(overrides)
    return args


def _placement_calls(adapter: FakeExecutionAdapter) -> list[str]:
    return [
        c["method"]
        for c in adapter.calls
        if c["method"] in ("place_entry", "place_algo_protective")
    ]


def _entry_calls(adapter: FakeExecutionAdapter) -> int:
    return len([c for c in adapter.calls if c["method"] == "place_entry"])


def test_check_binding_identity_passes_a_valid_callback_without_looking_at_expiry() -> None:
    from src.approval.binding import check_binding_identity

    result = check_binding_identity(**_binding_args())
    assert result.ok is True
    assert result.reason_code is None


def test_check_binding_identity_wrong_chat_is_invalidated_first() -> None:
    import dataclasses

    from src.approval.binding import check_binding_identity
    from src.domain.enums import RejectionReason

    case_input = _load_input()
    # A wrong chat AND a wrong hash: the chat gate runs before anything else.
    callback = dataclasses.replace(_build_callback(case_input), plan_hash="4" * 64)
    result = check_binding_identity(
        **_binding_args(callback=callback, authorized_chat_id=case_input["chat_id"] + 1)
    )
    assert result.ok is False
    assert result.reason_code == RejectionReason.INVALIDATED


def test_check_binding_identity_hash_version_and_token_mismatches() -> None:
    import dataclasses

    from src.approval.binding import check_binding_identity
    from src.domain.enums import RejectionReason

    callback = _build_callback(_load_input())
    stale = check_binding_identity(
        **_binding_args(callback=dataclasses.replace(callback, plan_hash="4" * 64))
    )
    assert (stale.ok, stale.reason_code) == (False, RejectionReason.STALE_SETUP)

    for field, value in (
        ("strategy_version", "other-version"),
        ("parameter_set_id", "other-set"),
        ("parameter_set_hash", "6" * 64),
        ("raw_token", "not-the-token"),
    ):
        result = check_binding_identity(
            **_binding_args(callback=dataclasses.replace(callback, **{field: value}))
        )
        assert (result.ok, result.reason_code) == (False, RejectionReason.INVALIDATED), field


async def test_replay_after_expiry_returns_the_stored_outcome_with_zero_adapter_calls() -> None:
    """D-15/D-16 (Open Q2): the stored outcome is looked up BEFORE the expiry gate."""
    case_input = _load_input()
    store = InMemoryExecutionIntentStore()
    first = await _run_plan(FakeExecutionAdapter(), intent_store=store)
    assert first.is_no_trade is False

    late = _parse_utc(case_input["expiry_utc"]) + timedelta(hours=1)
    risk_kwargs = _build_risk_kwargs(case_input)
    risk_kwargs["now_utc"] = late
    replay_adapter = FakeExecutionAdapter()
    replay = await _run_plan(
        replay_adapter, intent_store=store, now_utc=late, risk_kwargs=risk_kwargs
    )

    assert replay == first
    assert replay_adapter.calls == []


async def test_expiry_still_rejects_when_nothing_was_stored() -> None:
    case_input = _load_input()
    late = _parse_utc(case_input["expiry_utc"]) + timedelta(seconds=1)
    risk_kwargs = _build_risk_kwargs(case_input)
    risk_kwargs["now_utc"] = late
    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(adapter, now_utc=late, risk_kwargs=risk_kwargs)
    assert outcome.reason_code == "APPROVAL_EXPIRED"
    assert adapter.calls == []


async def test_stored_outcome_is_not_revealed_to_a_wrong_token_or_wrong_chat() -> None:
    """D-16: identity runs before the lookup, so a stranger gets INVALIDATED."""
    import dataclasses

    case_input = _load_input()
    store = InMemoryExecutionIntentStore()
    await _run_plan(FakeExecutionAdapter(), intent_store=store)

    bad_token = dataclasses.replace(_build_callback(case_input), raw_token="not-the-token")
    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(adapter, intent_store=store, callback=bad_token)
    assert (outcome.is_no_trade, outcome.reason_code) == (True, "INVALIDATED")
    assert adapter.calls == []

    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(
        adapter, intent_store=store, authorized_chat_id=case_input["chat_id"] + 1
    )
    assert (outcome.is_no_trade, outcome.reason_code) == (True, "INVALIDATED")
    assert adapter.calls == []


async def test_store_unavailable_on_lookup_fails_closed_with_zero_adapter_calls() -> None:
    from src.persistence.errors import StoreUnavailable

    from tests.support.intent_store_fakes import FailingIntentStore

    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(
        adapter, intent_store=FailingIntentStore("get_entry", StoreUnavailable("down"))
    )
    assert (outcome.is_no_trade, outcome.reason_code) == (True, "RECONCILIATION_REQUIRED")
    assert adapter.calls == []


async def test_store_unavailable_at_consume_places_nothing() -> None:
    from src.persistence.errors import StoreUnavailable

    from tests.support.intent_store_fakes import FailingIntentStore

    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(
        adapter,
        intent_store=FailingIntentStore("consume_and_record_entry_intent", StoreUnavailable("x")),
    )
    assert (outcome.is_no_trade, outcome.reason_code) == (True, "RECONCILIATION_REQUIRED")
    assert _placement_calls(adapter) == []


async def test_second_approval_of_the_same_plan_is_invalidated_without_placement() -> None:
    """IntentStateConflict at consume (a second approval for the same plan)."""
    from src.persistence.errors import IntentStateConflict

    from tests.support.intent_store_fakes import FailingIntentStore

    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(
        adapter,
        intent_store=FailingIntentStore(
            "consume_and_record_entry_intent", IntentStateConflict("uq_plan_role")
        ),
    )
    assert (outcome.is_no_trade, outcome.reason_code) == (True, "INVALIDATED")
    assert _placement_calls(adapter) == []


async def test_store_unavailable_at_entry_mark_sent_places_nothing() -> None:
    from src.persistence.errors import StoreUnavailable

    from tests.support.intent_store_fakes import FailingIntentStore

    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(
        adapter,
        intent_store=FailingIntentStore("mark_sent", StoreUnavailable("down"), role="ENTRY"),
    )
    assert (outcome.is_no_trade, outcome.reason_code) == (True, "RECONCILIATION_REQUIRED")
    assert _placement_calls(adapter) == []


async def test_successful_run_stores_entry_and_stop_loss_rows() -> None:
    from src.domain.enums import ExecutionIntentStatus
    from src.execution.order_ids import derive_algo_client_id

    case_input = _load_input()
    store = InMemoryExecutionIntentStore()
    outcome = await _run_plan(FakeExecutionAdapter(), intent_store=store)
    assert (outcome.is_no_trade, outcome.reason_code) == (False, "OK")

    entry = store.get_intent(approval_id=case_input["approval_id"], role="ENTRY")
    stop_loss = store.get_intent(approval_id=case_input["approval_id"], role="STOP_LOSS")
    assert entry is not None and stop_loss is not None
    assert entry.intent_status == ExecutionIntentStatus.ACKED
    assert entry.outcome is not None
    assert (entry.outcome.is_no_trade, entry.outcome.reason_code) == (False, "OK")
    assert stop_loss.intent_status == ExecutionIntentStatus.ACKED
    assert stop_loss.algo_client_id == derive_algo_client_id(
        plan_hash=case_input["plan_hash"], role="STOP_LOSS"
    )
    assert stop_loss.client_order_id is None
    assert stop_loss.intended_quantity is None
    assert stop_loss.side == "SELL"
    assert stop_loss.outcome is None


async def test_store_down_after_entry_ack_enters_safe_mode_and_still_places_the_sl() -> None:
    """Planner decision for D051: protection outranks the audit row (D034)."""
    from src.execution.order_ids import derive_algo_client_id
    from src.persistence.errors import StoreUnavailable

    from tests.support.intent_store_fakes import FailingIntentStore

    case_input = _load_input()
    adapter = FakeExecutionAdapter()
    safe_mode = RecordingSafeModeController()
    outcome = await _run_plan(
        adapter,
        safe_mode_controller=safe_mode,
        intent_store=FailingIntentStore("record_protective_intent", StoreUnavailable("down")),
    )

    assert (outcome.is_no_trade, outcome.reason_code) == (True, "RECONCILIATION_REQUIRED")
    assert safe_mode.entered_reasons == ["DB_FAILURE"]
    sl_calls = [c for c in adapter.calls if c["method"] == "place_algo_protective"]
    assert len(sl_calls) == 1
    assert sl_calls[0]["kwargs"]["client_algo_id"] == derive_algo_client_id(
        plan_hash=case_input["plan_hash"], role="STOP_LOSS"
    )
    assert "cancel_normal_order" not in [c["method"] for c in adapter.calls]


async def test_store_down_when_recording_the_entry_ack_still_places_the_sl() -> None:
    from src.persistence.errors import StoreUnavailable

    from tests.support.intent_store_fakes import FailingIntentStore

    adapter = FakeExecutionAdapter()
    safe_mode = RecordingSafeModeController()
    outcome = await _run_plan(
        adapter,
        safe_mode_controller=safe_mode,
        intent_store=FailingIntentStore("record_result", StoreUnavailable("down"), role="ENTRY"),
    )
    assert (outcome.is_no_trade, outcome.reason_code) == (True, "RECONCILIATION_REQUIRED")
    assert safe_mode.entered_reasons == ["DB_FAILURE"]
    assert len([c for c in adapter.calls if c["method"] == "place_algo_protective"]) == 1


async def test_store_down_and_sl_unconfirmed_still_cancels_the_entry() -> None:
    from src.persistence.errors import StoreUnavailable

    from tests.support.intent_store_fakes import FailingIntentStore

    adapter = FakeExecutionAdapter(algo_response={"algo_status": "REJECTED"})
    safe_mode = RecordingSafeModeController()
    outcome = await _run_plan(
        adapter,
        safe_mode_controller=safe_mode,
        intent_store=FailingIntentStore("record_protective_intent", StoreUnavailable("down")),
    )
    assert (outcome.is_no_trade, outcome.reason_code) == (True, "RECONCILIATION_REQUIRED")
    assert safe_mode.entered_reasons == ["DB_FAILURE", "ENTRY_WITHOUT_PROTECTIVE"]
    assert [c["method"] for c in adapter.calls][-1] == "cancel_normal_order"


class _StoreDownJournal:
    """A journal whose `record` always raises `StoreUnavailable` (database outage)."""

    def __init__(self) -> None:
        self.attempts = 0

    def record(self, event: Any) -> None:
        from src.persistence.errors import StoreUnavailable

        self.attempts += 1
        raise StoreUnavailable("database unavailable")


def _real_controller_with_down_journal() -> tuple[Any, _StoreDownJournal]:
    """The REAL `SafeModeController` wired to a journal that raises (17-REVIEW CR-01)."""
    from src.reconcile.safe_mode import SafeModeController

    class _NoOpTruth:
        async def snapshot_open_normal_orders(self, *, symbol: Any = None) -> list[Any]:
            return []

        async def snapshot_open_algo_orders(self, *, symbol: Any = None) -> list[Any]:
            return []

        async def snapshot_positions(self, *, symbol: Any = None) -> list[Any]:
            return []

    journal = _StoreDownJournal()
    return SafeModeController(adapter=_NoOpTruth(), journal=journal), journal


async def test_cr01_db_outage_after_entry_ack_still_places_the_sl_with_real_controller() -> None:
    """17-REVIEW CR-01: the real controller journals through the same failing store.

    The controller sets its flag before journaling, so the journal error must not
    abort the manager before the stop loss is placed.
    """
    from src.execution.order_ids import derive_algo_client_id
    from src.persistence.errors import StoreUnavailable

    from tests.support.intent_store_fakes import FailingIntentStore

    case_input = _load_input()
    adapter = FakeExecutionAdapter()
    controller, journal = _real_controller_with_down_journal()
    outcome = await _run_plan(
        adapter,
        safe_mode_controller=controller,
        intent_store=FailingIntentStore("record_result", StoreUnavailable("down"), role="ENTRY"),
    )

    assert (outcome.is_no_trade, outcome.reason_code) == (True, "RECONCILIATION_REQUIRED")
    assert controller.in_safe_mode is True
    assert journal.attempts >= 1  # the audit row WAS attempted and lost
    sl_calls = [c for c in adapter.calls if c["method"] == "place_algo_protective"]
    assert len(sl_calls) == 1
    assert sl_calls[0]["kwargs"]["client_algo_id"] == derive_algo_client_id(
        plan_hash=case_input["plan_hash"], role="STOP_LOSS"
    )


async def test_cr01_db_outage_at_sl_intent_still_places_the_sl_with_real_controller() -> None:
    from src.persistence.errors import StoreUnavailable

    from tests.support.intent_store_fakes import FailingIntentStore

    adapter = FakeExecutionAdapter()
    controller, _journal = _real_controller_with_down_journal()
    outcome = await _run_plan(
        adapter,
        safe_mode_controller=controller,
        intent_store=FailingIntentStore("record_protective_intent", StoreUnavailable("down")),
    )

    assert (outcome.is_no_trade, outcome.reason_code) == (True, "RECONCILIATION_REQUIRED")
    assert controller.in_safe_mode is True
    assert len([c for c in adapter.calls if c["method"] == "place_algo_protective"]) == 1


async def test_cr01_failing_journal_at_entry_state_unknown_still_records_and_finalizes() -> None:
    """17-REVIEW CR-01 (call site ENTRY_STATE_UNKNOWN): the audit-row failure must not
    skip the intent bookkeeping that follows the SAFE_MODE entry."""
    from src.domain.enums import ExecutionIntentStatus

    case_input = _load_input()
    store = InMemoryExecutionIntentStore()
    adapter = FakeExecutionAdapter()
    adapter.entry_exceptions.append(TimeoutError("status unknown"))
    adapter.query_exceptions.append(RuntimeError("-2013 Order does not exist"))
    controller, journal = _real_controller_with_down_journal()

    outcome = await _run_plan(adapter, safe_mode_controller=controller, intent_store=store)

    assert (outcome.is_no_trade, outcome.reason_code) == (True, "RECONCILIATION_REQUIRED")
    assert controller.in_safe_mode is True
    assert journal.attempts >= 1
    entry = store.get_entry(approval_id=case_input["approval_id"])
    assert entry is not None
    assert entry.intent_status == ExecutionIntentStatus.UNKNOWN
    assert entry.outcome is not None
    assert entry.outcome.reason_code == "RECONCILIATION_REQUIRED"
    assert "place_algo_protective" not in [c["method"] for c in adapter.calls]


async def test_cr01_failing_journal_at_entry_without_protective_still_cancels_the_entry() -> None:
    """17-REVIEW CR-01 (call site ENTRY_WITHOUT_PROTECTIVE): the unprotected entry must
    still be cancelled when the SAFE_MODE audit row cannot be written."""
    adapter = FakeExecutionAdapter(algo_response={"algo_status": "REJECTED"})
    controller, journal = _real_controller_with_down_journal()

    outcome = await _run_plan(adapter, safe_mode_controller=controller)

    assert (outcome.is_no_trade, outcome.reason_code) == (True, "ENTRY_WITHOUT_PROTECTIVE")
    assert controller.in_safe_mode is True
    assert journal.attempts >= 1
    assert [c["method"] for c in adapter.calls][-1] == "cancel_normal_order"


async def test_unconfirmed_sl_leaves_the_stop_loss_row_unknown() -> None:
    from src.domain.enums import ExecutionIntentStatus

    case_input = _load_input()
    store = InMemoryExecutionIntentStore()
    adapter = FakeExecutionAdapter(algo_response={"algo_status": "REJECTED"})
    safe_mode = RecordingSafeModeController()
    outcome = await _run_plan(adapter, safe_mode_controller=safe_mode, intent_store=store)

    assert (outcome.is_no_trade, outcome.reason_code) == (True, "ENTRY_WITHOUT_PROTECTIVE")
    assert safe_mode.entered_reasons == ["ENTRY_WITHOUT_PROTECTIVE"]
    assert [c["method"] for c in adapter.calls][-1] == "cancel_normal_order"
    stop_loss = store.get_intent(approval_id=case_input["approval_id"], role="STOP_LOSS")
    assert stop_loss is not None
    assert stop_loss.intent_status == ExecutionIntentStatus.UNKNOWN
    entry = store.get_entry(approval_id=case_input["approval_id"])
    assert entry is not None and entry.outcome is not None
    assert entry.outcome.reason_code == "ENTRY_WITHOUT_PROTECTIVE"


async def test_a_simulated_crash_propagates_unchanged() -> None:
    import pytest

    from tests.support.intent_store_fakes import CrashAfter, SimulatedCrash

    for step in ("consume", "entry_sent", "entry_result", "sl_intent", "sl_sent", "sl_result"):
        store = CrashAfter(InMemoryExecutionIntentStore(), step=step)
        with pytest.raises(SimulatedCrash):
            await _run_plan(FakeExecutionAdapter(), intent_store=store)


async def test_restart_after_a_crash_never_resends_the_entry() -> None:
    import pytest

    from tests.support.intent_store_fakes import CrashAfter, SimulatedCrash

    case_input = _load_input()
    for step, entry_calls in (
        ("consume", 0),
        ("entry_sent", 0),
        ("entry_result", 1),
        ("sl_intent", 1),
        ("sl_sent", 1),
        ("sl_result", 1),
    ):
        inner = InMemoryExecutionIntentStore()
        adapter = FakeExecutionAdapter()
        with pytest.raises(SimulatedCrash):
            await _run_plan(adapter, intent_store=CrashAfter(inner, step=step))
        assert _entry_calls(adapter) == entry_calls, step
        assert inner.get_entry(approval_id=case_input["approval_id"]) is not None

        restarted = await _run_plan(adapter, intent_store=inner)
        assert (restarted.is_no_trade, restarted.reason_code) == (
            True,
            "RECONCILIATION_REQUIRED",
        ), step
        assert _entry_calls(adapter) == entry_calls, step


def test_intent_status_changes_go_through_the_transition_tables() -> None:
    root = Path(__file__).parent.parent
    pg_source = (root / "src" / "persistence" / "execution_state.py").read_text(encoding="utf-8")
    protocol_source = (root / "src" / "execution" / "intent_store.py").read_text(encoding="utf-8")
    assert "TransitionKind.EXECUTION_INTENT" in pg_source
    assert "ALLOWED_PREDECESSORS" not in pg_source
    assert "ALLOWED_PREDECESSORS" not in protocol_source


def test_order_ids_do_not_claim_exchange_side_deduplication() -> None:
    """D-13, F-951, research C18: the persisted intent is the duplicate-entry guard."""
    source = (Path(__file__).parent.parent / "src" / "execution" / "order_ids.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    assert "dedupe retries" not in lowered
    assert "impossible by construction" not in lowered
    assert "open orders" in lowered


# --------------------------------------------------------------------------- #
# Phase 19 plan 19-13, Task 1 - LivePlacementContext and the binding gate (1c).
# --------------------------------------------------------------------------- #


def test_fixture_plan_hash_is_the_rederived_hash() -> None:
    """The fixture's stored plan hash is the planner's own hash of the plan fields (D-01)."""
    case_input = _load_input()
    assert case_input["plan_hash"] == _plan_hash_of(case_input)
    assert _load_expected()["plan_hash"] == case_input["plan_hash"]


def test_fixture_plan_quantity_covers_the_risk_sized_quantity() -> None:
    """F-203: the plan quantity is no longer below what the risk pipeline sizes."""
    case_input = _load_input()
    assert _coerce_decimal(case_input["quantity_after_rounding"], "q") == Decimal("2.415")


def test_gate_kwarg_keys_are_unchanged() -> None:
    """Plan 19-13 adds ONE keyword (`live_context`); the gate-kwargs key set is untouched."""
    from src.execution import manager

    assert manager._GATE_KWARG_KEYS == frozenset(
        {"open_algo_count", "planned_leg_count", "positions_reconciled"}
    )


def test_execute_approved_plan_takes_live_context_as_a_required_keyword() -> None:
    import inspect

    from src.execution import manager

    parameter = inspect.signature(manager.execute_approved_plan).parameters["live_context"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


async def test_missing_live_context_raises_before_any_adapter_call() -> None:
    import pytest

    adapter = FakeExecutionAdapter()
    with pytest.raises(ValueError, match="live_context is required"):
        await _run_plan(adapter, live_context=None)
    assert adapter.calls == []


def test_live_context_validates_every_field() -> None:
    import dataclasses

    import pytest
    from src.execution.live_context import LivePlacementContext

    context = _build_live_context(_load_input())
    assert isinstance(context, LivePlacementContext)
    fields = {f.name: getattr(context, f.name) for f in dataclasses.fields(context)}
    assert set(fields) == {
        "signal",
        "plan_constraint_snapshot",
        "execution_limits",
        "protection_registry",
        "latest_closed_bar_close",
        "gtd_clock_margin",
        "tp1_quantity_fraction",
    }
    # Every field is required: building without one raises TypeError.
    for name in fields:
        partial = {k: v for k, v in fields.items() if k != name}
        with pytest.raises(TypeError):
            LivePlacementContext(**partial)
    bad_values: dict[str, Any] = {
        "signal": object(),
        "plan_constraint_snapshot": object(),
        "execution_limits": object(),
        "protection_registry": object(),
        "latest_closed_bar_close": 101.5,
        "gtd_clock_margin": 0.5,
        "tp1_quantity_fraction": 0.5,
    }
    for name, bad in bad_values.items():
        with pytest.raises(TypeError):
            LivePlacementContext(**{**fields, name: bad})
    for name, bad in (
        ("latest_closed_bar_close", Decimal("0")),
        ("latest_closed_bar_close", Decimal("NaN")),
        ("gtd_clock_margin", timedelta(seconds=-1)),
        ("tp1_quantity_fraction", Decimal("0")),
        ("tp1_quantity_fraction", Decimal("1.01")),
    ):
        with pytest.raises(ValueError):
            LivePlacementContext(**{**fields, name: bad})
    # None is the explicit "bar close not available" value; a fraction of exactly 1 is allowed.
    assert LivePlacementContext(**{**fields, "latest_closed_bar_close": None}) is not None
    assert LivePlacementContext(**{**fields, "tp1_quantity_fraction": Decimal("1")}) is not None


def test_live_context_module_is_pure() -> None:
    import ast

    source = (Path(__file__).parents[1] / "src" / "execution" / "live_context.py").read_text(
        encoding="utf-8"
    )
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert imported <= {
        "__future__",
        "dataclasses",
        "datetime",
        "decimal",
        "src.domain.signal",
        "src.execution.constraint_snapshot",
        "src.execution.execution_limits",
        "src.execution.protection",
    }


async def test_golden_case_with_the_live_context_still_places() -> None:
    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(adapter)
    assert (outcome.is_no_trade, outcome.reason_code) == (False, "OK")


def _binding_case_variants() -> list[tuple[str, dict[str, Any], str]]:
    """(label, `_run_plan` overrides, expected reason) for each Task 1 binding refusal."""
    import dataclasses

    case_input = _load_input()
    other_plan_hash = "4" * 64

    def risk_with_side(side: str) -> dict[str, Any]:
        risk_kwargs = _build_risk_kwargs(case_input)
        risk_kwargs["candidate_position_side"] = side
        return risk_kwargs

    def risk_with_symbol(symbol: str) -> dict[str, Any]:
        risk_kwargs = _build_risk_kwargs(case_input)
        risk_kwargs["constraint_snapshot"] = dataclasses.replace(
            risk_kwargs["constraint_snapshot"], symbol=symbol
        )
        return risk_kwargs

    def risk_with_synthetic_hash() -> dict[str, Any]:
        risk_kwargs = _build_risk_kwargs(case_input)
        risk_kwargs["trade_plan"] = dataclasses.replace(
            risk_kwargs["trade_plan"], plan_hash=other_plan_hash
        )
        return risk_kwargs

    live = _build_live_context(case_input)
    return [
        (
            "caller side SHORT on a LONG plan",
            {"risk_kwargs": risk_with_side("SHORT")},
            "PLAN_SIDE_MISMATCH",
        ),
        (
            "caller symbol ETHUSDT",
            {"risk_kwargs": risk_with_symbol("ETHUSDT")},
            "PLAN_SYMBOL_MISMATCH",
        ),
        (
            "plan snapshot symbol ETHUSDT",
            {
                "live_context": dataclasses.replace(
                    live,
                    plan_constraint_snapshot=dataclasses.replace(
                        live.plan_constraint_snapshot, symbol="ETHUSDT"
                    ),
                )
            },
            "PLAN_SYMBOL_MISMATCH",
        ),
        (
            "plan snapshot of another plan",
            {
                "live_context": dataclasses.replace(
                    live,
                    plan_constraint_snapshot=dataclasses.replace(
                        live.plan_constraint_snapshot, trade_plan_id="tp_other"
                    ),
                )
            },
            "PLAN_SYMBOL_MISMATCH",
        ),
        (
            "synthetic plan hash",
            {
                "risk_kwargs": risk_with_synthetic_hash(),
                "callback": dataclasses.replace(
                    _build_callback(case_input), plan_hash=other_plan_hash
                ),
                "approval": dataclasses.replace(
                    _build_approval(case_input), request_hash=other_plan_hash
                ),
            },
            "STALE_SETUP",
        ),
        (
            "signal of another strategy version",
            {
                "live_context": dataclasses.replace(
                    live, signal=_build_signal(case_input, strategy_version="v9.9.9")
                )
            },
            "PLAN_SIGNAL_MISMATCH",
        ),
        (
            "signal of another signal id",
            {
                "live_context": dataclasses.replace(
                    live, signal=_build_signal(case_input, signal_id="sig_other")
                )
            },
            "PLAN_SIGNAL_MISMATCH",
        ),
        (
            "signal direction SHORT against LONG geometry",
            {
                "live_context": dataclasses.replace(
                    live, signal=_build_signal(case_input, direction="SHORT")
                )
            },
            "PLAN_SIDE_MISMATCH",
        ),
    ]


async def test_binding_refusals_are_no_trade_with_zero_calls_and_no_entry_row() -> None:
    case_input = _load_input()
    for label, overrides, reason in _binding_case_variants():
        adapter = FakeExecutionAdapter()
        store = InMemoryExecutionIntentStore()
        outcome = await _run_plan(adapter, intent_store=store, **overrides)
        assert (outcome.is_no_trade, outcome.reason_code) == (True, reason), label
        assert adapter.calls == [], label
        assert store.get_entry(approval_id=case_input["approval_id"]) is None, label


async def test_a_tampered_working_type_is_refused_before_any_adapter_call() -> None:
    """D-04: the snapshot cannot be built with another working type, so tamper after the fact."""
    import dataclasses

    from src.execution.binding import WORKING_TYPE_NOT_MARK_PRICE, check_working_type

    assert check_working_type("MARK_PRICE") is None
    assert check_working_type("CONTRACT_PRICE") == WORKING_TYPE_NOT_MARK_PRICE

    case_input = _load_input()
    live = _build_live_context(case_input)
    snapshot = dataclasses.replace(live.plan_constraint_snapshot)
    object.__setattr__(snapshot, "working_type", "CONTRACT_PRICE")
    adapter = FakeExecutionAdapter()
    store = InMemoryExecutionIntentStore()
    outcome = await _run_plan(
        adapter,
        intent_store=store,
        live_context=dataclasses.replace(live, plan_constraint_snapshot=snapshot),
    )
    assert (outcome.is_no_trade, outcome.reason_code) == (True, WORKING_TYPE_NOT_MARK_PRICE)
    assert adapter.calls == []
    assert store.get_entry(approval_id=case_input["approval_id"]) is None


async def test_replay_returns_the_stored_outcome_before_the_binding_gate() -> None:
    """APRV-02 / D-09: the replay lookup precedes gate 1c, so a refusing context changes nothing."""
    import dataclasses

    case_input = _load_input()
    store = InMemoryExecutionIntentStore()
    first = await _run_plan(FakeExecutionAdapter(), intent_store=store)
    assert (first.is_no_trade, first.reason_code) == (False, "OK")

    refusing = dataclasses.replace(
        _build_live_context(case_input), signal=_build_signal(case_input, strategy_version="v9.9.9")
    )
    replay_adapter = FakeExecutionAdapter()
    replay = await _run_plan(replay_adapter, intent_store=store, live_context=refusing)
    assert replay == first
    assert replay_adapter.calls == []


# --------------------------------------------------------------------------- #
# Phase 19 plan 19-13, Task 2 - limits, quantity, snapped geometry, TP1 sizeable, live
# reads and the Hedge refusal. Every refusal happens before the approval is consumed.
# --------------------------------------------------------------------------- #


def _open_order(symbol: str = "BTCUSDT") -> Any:
    from src.adapters.binance_usdm import OpenOrderSnapshot

    return OpenOrderSnapshot(
        symbol=symbol,
        client_order_id="x-someone-else",
        exchange_order_id="9001",
        side="BUY",
        position_side="BOTH",
        order_type="LIMIT",
        time_in_force="GTC",
        status="NEW",
        quantity=Decimal("0.100"),
        price=Decimal("99.00"),
        stop_price=None,
        reduce_only=False,
        close_position=False,
        working_type=None,
        price_protect=None,
        update_time_utc=datetime(2026, 9, 19, 10, 0, tzinfo=UTC),
    )


def _open_algo(symbol: str = "BTCUSDT") -> Any:
    from src.adapters.binance_usdm import OpenAlgoOrderSnapshot

    return OpenAlgoOrderSnapshot(
        symbol=symbol,
        client_algo_id="xa-someone-else",
        algo_id="9002",
        algo_type="CONDITIONAL",
        order_type="STOP_MARKET",
        side="SELL",
        position_side="BOTH",
        time_in_force="GTC",
        algo_status="NEW",
        quantity=Decimal("0"),
        trigger_price=Decimal("90.00"),
        price=None,
        trigger_time_utc=None,
        working_type="MARK_PRICE",
        close_position=True,
        reduce_only=False,
        update_time_utc=datetime(2026, 9, 19, 10, 0, tzinfo=UTC),
    )


def _reads_only(adapter: FakeExecutionAdapter) -> list[str]:
    return [c["method"] for c in adapter.calls]


def _case_with(**changes: Any) -> dict[str, Any]:
    """A copy of the golden case; hashed fields re-derive the plan hash through the builders."""
    return {**_load_input(), **changes}


async def _assert_refused_then_placeable(
    *,
    label: str,
    reason: str,
    adapter: FakeExecutionAdapter,
    expected_calls: list[str],
    case_input: dict[str, Any] | None = None,
    **overrides: Any,
) -> None:
    """The refusal is NO_TRADE `reason`, leaves no ENTRY row, and a corrected call still places.

    The corrected call reuses the SAME intent store, so a consumed approval would replay the
    stored refusal instead of placing: it proves the approval was never consumed.
    """
    case = case_input if case_input is not None else _load_input()
    store = InMemoryExecutionIntentStore()
    outcome = await _run_plan(adapter, case_input=case_input, intent_store=store, **overrides)
    assert (outcome.is_no_trade, outcome.reason_code) == (True, reason), label
    assert _reads_only(adapter) == expected_calls, label
    assert "place_entry" not in _reads_only(adapter), label
    assert "place_algo_protective" not in _reads_only(adapter), label
    assert store.get_entry(approval_id=case["approval_id"]) is None, label

    # The corrected call is the unedited golden case under the same approval id.
    placed = await _run_plan(FakeExecutionAdapter(), intent_store=store)
    assert (placed.is_no_trade, placed.reason_code) == (False, "OK"), label
    assert store.get_entry(approval_id=case["approval_id"]) is not None, label


async def test_golden_case_reads_precede_the_position_mode_and_the_placement() -> None:
    """Plan 19-13, gate 5e: the reads are keyed by the bound symbol and run in a fixed order."""
    case_input = _load_input()
    registry = StubProtectionRegistry()
    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(
        adapter, live_context=_build_live_context(case_input, protection_registry=registry)
    )
    assert (outcome.is_no_trade, outcome.reason_code) == (False, "OK")
    assert _reads_only(adapter)[:4] == [*PRE_PLACEMENT_READS, "get_position_mode"]
    for call in adapter.calls[:3]:
        assert call["kwargs"] == {"symbol": "BTCUSDT"}
    assert registry.block_checks == 1


@pytest.mark.parametrize(
    "limit",
    [
        "max_unprotected_ms",
        "entry_terminal_timeout_ms",
        "min_remaining_validity_seconds",
        "max_mark_price_age_ms",
    ],
)
async def test_unset_limit_refuses_with_zero_adapter_calls(limit: str) -> None:
    """D-07 / D-13 (T-19-34): any NOT_CONFIGURED limit stops the live path before any call."""
    from tests.support import execution_limits as test_limits

    case_input = _load_input()
    live = _build_live_context(
        case_input, execution_limits=test_limits.test_only_execution_limits(**{limit: None})
    )
    adapter = FakeExecutionAdapter()
    store = InMemoryExecutionIntentStore()
    outcome = await _run_plan(adapter, intent_store=store, live_context=live)
    assert (outcome.is_no_trade, outcome.reason_code) == (True, "LIMITS_NOT_CONFIGURED")
    assert adapter.calls == []
    assert store.get_entry(approval_id=case_input["approval_id"]) is None


async def test_the_committed_not_configured_limits_file_refuses_every_live_placement() -> None:
    """The consequence recorded for the owner: with the committed file nothing places."""
    from src.execution.execution_limits import load_execution_limits

    path = Path(__file__).parents[1] / "config" / "execution" / "execution-limits-v1.toml"
    limits = load_execution_limits(path)
    assert limits.unset_keys() != ()
    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(
        adapter, live_context=_build_live_context(_load_input(), execution_limits=limits)
    )
    assert (outcome.is_no_trade, outcome.reason_code) == (True, "LIMITS_NOT_CONFIGURED")
    assert adapter.calls == []


async def test_risk04_quantity_above_the_approved_quantity_is_never_clipped() -> None:
    """D-02 / RISK-04 / T-19-32: the risk-sized quantity may not exceed the approved one."""
    import dataclasses

    case_input = _load_input()
    risk_kwargs = _build_risk_kwargs(case_input)
    risk_kwargs["trade_plan"] = dataclasses.replace(
        risk_kwargs["trade_plan"], quantity_after_rounding=Decimal("2.414")
    )
    await _assert_refused_then_placeable_with_risk(
        label="plan quantity one step below the sized quantity",
        reason="QUANTITY_ABOVE_APPROVED",
        risk_kwargs=risk_kwargs,
    )


async def _assert_refused_then_placeable_with_risk(
    *, label: str, reason: str, risk_kwargs: dict[str, Any]
) -> None:
    """Refusal check for a risk_kwargs edit that is not a hashed-field edit (no re-hash needed)."""
    case_input = _load_input()
    adapter = FakeExecutionAdapter()
    store = InMemoryExecutionIntentStore()
    outcome = await _run_plan(adapter, intent_store=store, risk_kwargs=risk_kwargs)
    assert (outcome.is_no_trade, outcome.reason_code) == (True, reason), label
    assert adapter.calls == [], label
    assert store.get_entry(approval_id=case_input["approval_id"]) is None, label
    placed = await _run_plan(FakeExecutionAdapter(), intent_store=store)
    assert (placed.is_no_trade, placed.reason_code) == (False, "OK"), label


async def test_risk04_a_quantity_equal_to_the_approved_quantity_places() -> None:
    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(adapter)
    entry = next(c for c in adapter.calls if c["method"] == "place_entry")
    assert entry["kwargs"]["quantity"] == Decimal("2.415")
    assert outcome.is_no_trade is False


async def test_a_stop_within_one_tick_of_the_zone_edge_is_refused_after_the_snap() -> None:
    """D-03 / G4-020: stop 99.999 snaps UP to 100.00 = the zone edge, no longer outside it."""
    case_input = _case_with(stop_loss_price="99.999", quantity_after_rounding="100")
    adapter = FakeExecutionAdapter(case_input=case_input)
    await _assert_refused_then_placeable(
        label="stop snaps onto the zone edge",
        reason="GEOMETRY_INVALID_AFTER_SNAP",
        adapter=adapter,
        expected_calls=[],
        case_input=case_input,
    )


async def test_a_stop_one_full_tick_outside_the_zone_edge_places() -> None:
    case_input = _case_with(stop_loss_price="99.98", quantity_after_rounding="100")
    adapter = FakeExecutionAdapter(case_input=case_input)
    outcome = await _run_plan(adapter, case_input=case_input)
    assert (outcome.is_no_trade, outcome.reason_code) == (False, "OK")


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"min_quantity": "1.500"}, "MIN_QTY_REJECT"),
        ({"min_notional": "200.00"}, "NOTIONAL_REJECT"),
    ],
)
async def test_an_unsizeable_tp1_refuses_the_plan_with_no_single_tp_fallback(
    changes: dict[str, str], reason: str
) -> None:
    """O-03 auto default / backtest D-27: TP1 at 50% of 2.415 is below the filter -> NO_TRADE."""
    case_input = _case_with(**changes)
    adapter = FakeExecutionAdapter(case_input=case_input)
    store = InMemoryExecutionIntentStore()
    outcome = await _run_plan(adapter, case_input=case_input, intent_store=store)
    assert (outcome.is_no_trade, outcome.reason_code) == (True, reason)
    assert adapter.calls == []
    assert store.get_entry(approval_id=case_input["approval_id"]) is None
    # The entry itself is sizeable: with TP1 sized at the whole position the plan places.
    whole = _build_live_context(case_input, tp1_quantity_fraction=Decimal("1"))
    placed = await _run_plan(
        FakeExecutionAdapter(case_input=case_input),
        case_input=case_input,
        live_context=whole,
        intent_store=store,
    )
    assert (placed.is_no_trade, placed.reason_code) == (False, "OK")


async def test_the_tp1_check_follows_the_live_context_fraction() -> None:
    """A fraction that leaves TP1 unsizeable refuses; this is the same frozen sizing function."""
    case_input = _case_with(min_quantity="1.500")
    tiny = _build_live_context(case_input, tp1_quantity_fraction=Decimal("0.1"))
    adapter = FakeExecutionAdapter(case_input=case_input)
    outcome = await _run_plan(adapter, case_input=case_input, live_context=tiny)
    assert (outcome.is_no_trade, outcome.reason_code) == (True, "MIN_QTY_REJECT")
    assert adapter.calls == []


def _mark_cases() -> list[tuple[str, dict[str, Any], str]]:
    case_input = _load_input()
    stale = _mark_reading_for(
        case_input,
        exchange_time_utc=_parse_utc(case_input["now_utc"]) - timedelta(milliseconds=4322),
    )
    future = _mark_reading_for(
        case_input, exchange_time_utc=_parse_utc(case_input["now_utc"]) + timedelta(seconds=1)
    )
    return [
        ("mark at the stop trigger", {"mark": Decimal("98.00")}, "MARK_PRICE_CROSSED_STOP"),
        ("mark below the stop", {"mark": Decimal("97.50")}, "MARK_PRICE_CROSSED_STOP"),
        ("mark above the zone", {"mark": Decimal("102.01")}, "MARK_PRICE_OUTSIDE_ZONE"),
        ("mark below the zone", {"mark": Decimal("99.50")}, "MARK_PRICE_OUTSIDE_ZONE"),
        (
            "mark read raises",
            {"mark_exception": TimeoutError("read timeout")},
            "MARK_PRICE_UNAVAILABLE",
        ),
        ("mark read is stale", {"reading": stale}, "MARK_PRICE_UNAVAILABLE"),
        ("mark read is from the future", {"reading": future}, "MARK_PRICE_UNAVAILABLE"),
        ("mark read is unusable", {"reading": object()}, "MARK_PRICE_UNAVAILABLE"),
    ]


async def test_mark_price_refusals_make_only_the_reads_and_leave_the_approval_unconsumed() -> None:
    case_input = _load_input()
    for label, spec, reason in _mark_cases():
        adapter = FakeExecutionAdapter()
        if "mark" in spec:
            adapter.mark_reading = _mark_reading_for(case_input, mark_price=spec["mark"])
        if "mark_exception" in spec:
            adapter.mark_exception = spec["mark_exception"]
        if "reading" in spec:
            adapter.mark_reading = spec["reading"]
        await _assert_refused_then_placeable(
            label=label, reason=reason, adapter=adapter, expected_calls=PRE_PLACEMENT_READS
        )


async def test_risk04_a_position_on_the_symbol_is_refused() -> None:
    """RISK-04 / D-05: a reconciled position on the symbol blocks a second plan on it."""
    from src.risk.types import OpenPosition

    case_input = _load_input()
    risk_kwargs = _build_risk_kwargs(case_input)
    risk_kwargs["open_positions"] = [
        OpenPosition(
            symbol="BTCUSDT",
            position_side="LONG",
            open_risk=Decimal("1.00"),
            daily_pnl_contribution=Decimal("0"),
        )
    ]
    adapter = FakeExecutionAdapter()
    store = InMemoryExecutionIntentStore()
    outcome = await _run_plan(adapter, intent_store=store, risk_kwargs=risk_kwargs)
    assert (outcome.is_no_trade, outcome.reason_code) == (True, "SYMBOL_HAS_POSITION")
    assert "place_entry" not in _reads_only(adapter)
    assert store.get_entry(approval_id=case_input["approval_id"]) is None


async def test_a_position_on_another_symbol_does_not_block() -> None:
    from src.risk.types import OpenPosition

    risk_kwargs = _build_risk_kwargs(_load_input())
    risk_kwargs["open_positions"] = [
        OpenPosition(
            symbol="ETHUSDT",
            position_side="LONG",
            open_risk=Decimal("1.00"),
            daily_pnl_contribution=Decimal("0"),
        )
    ]
    outcome = await _run_plan(FakeExecutionAdapter(), risk_kwargs=risk_kwargs)
    assert (outcome.is_no_trade, outcome.reason_code) == (False, "OK")


async def test_open_orders_and_unreadable_order_state_refuse() -> None:
    cases: list[tuple[str, dict[str, Any], str]] = [
        (
            "open normal order on the symbol",
            {"open_normal_orders": [_open_order()]},
            "SYMBOL_HAS_OPEN_ORDER",
        ),
        (
            "open algo order on the symbol",
            {"open_algo_orders": [_open_algo()]},
            "SYMBOL_HAS_OPEN_ORDER",
        ),
        (
            "normal order read raises",
            {"normal_orders_exception": TimeoutError("read timeout")},
            "SYMBOL_STATE_UNAVAILABLE",
        ),
        (
            "algo order read raises",
            {"algo_orders_exception": TimeoutError("read timeout")},
            "SYMBOL_STATE_UNAVAILABLE",
        ),
    ]
    for label, attrs, reason in cases:
        adapter = FakeExecutionAdapter()
        for name, value in attrs.items():
            setattr(adapter, name, value)
        await _assert_refused_then_placeable(
            label=label, reason=reason, adapter=adapter, expected_calls=PRE_PLACEMENT_READS
        )


async def test_an_order_on_another_symbol_does_not_block() -> None:
    adapter = FakeExecutionAdapter()
    adapter.open_normal_orders = [_open_order("ETHUSDT")]
    adapter.open_algo_orders = [_open_algo("ETHUSDT")]
    outcome = await _run_plan(adapter)
    assert (outcome.is_no_trade, outcome.reason_code) == (False, "OK")


async def test_an_unprotected_position_anywhere_blocks_a_new_entry() -> None:
    """D-11: the registry's account-wide `blocks_new_entries()` refuses (UNPROTECTED first)."""
    case_input = _load_input()
    live = _build_live_context(case_input, protection_registry=StubProtectionRegistry(blocks=True))
    adapter = FakeExecutionAdapter()
    adapter.open_normal_orders = [_open_order()]  # also a busy symbol: UNPROTECTED wins
    store = InMemoryExecutionIntentStore()
    outcome = await _run_plan(adapter, live_context=live, intent_store=store)
    assert (outcome.is_no_trade, outcome.reason_code) == (True, "UNPROTECTED_POSITION_EXISTS")
    assert "place_entry" not in _reads_only(adapter)
    assert store.get_entry(approval_id=case_input["approval_id"]) is None


async def test_plan_status_deny_list_refuses_and_approved_plans_are_not_refused() -> None:
    """D-09: EXPIRED / INVALIDATED / SUPERSEDED refuse; an executed plan is APPROVED and passes."""
    import dataclasses

    from src.domain.enums import TradePlanStatus

    for status in (
        TradePlanStatus.EXPIRED,
        TradePlanStatus.INVALIDATED,
        TradePlanStatus.SUPERSEDED,
    ):
        risk_kwargs = _build_risk_kwargs(_load_input())
        risk_kwargs["trade_plan"] = dataclasses.replace(risk_kwargs["trade_plan"], status=status)
        adapter = FakeExecutionAdapter()
        store = InMemoryExecutionIntentStore()
        outcome = await _run_plan(adapter, intent_store=store, risk_kwargs=risk_kwargs)
        assert (outcome.is_no_trade, outcome.reason_code) == (True, "PLAN_STATUS_INVALID"), status
        assert "place_entry" not in _reads_only(adapter)
        assert store.get_entry(approval_id=_load_input()["approval_id"]) is None
    for status in (
        TradePlanStatus.READY,
        TradePlanStatus.APPROVAL_PENDING,
        TradePlanStatus.APPROVED,
    ):
        risk_kwargs = _build_risk_kwargs(_load_input())
        risk_kwargs["trade_plan"] = dataclasses.replace(risk_kwargs["trade_plan"], status=status)
        outcome = await _run_plan(FakeExecutionAdapter(), risk_kwargs=risk_kwargs)
        assert (outcome.is_no_trade, outcome.reason_code) == (False, "OK"), status


async def test_invalidation_refusals() -> None:
    """D-08: an invalidated Signal, a bar close beyond the level or no bar close refuses."""
    import dataclasses

    case_input = _load_input()
    base = _build_live_context(case_input)
    invalidated_at = _parse_utc(case_input["now_utc"]) - timedelta(minutes=1)
    variants: list[tuple[str, Any, str]] = [
        (
            "signal invalidated",
            dataclasses.replace(
                base, signal=_build_signal(case_input, invalidated_at_utc=invalidated_at)
            ),
            "PLAN_INVALIDATED_BEFORE_PLACEMENT",
        ),
        (
            "bar closed below the LONG level",
            dataclasses.replace(base, latest_closed_bar_close=Decimal("97.99")),
            "PLAN_INVALIDATED_BEFORE_PLACEMENT",
        ),
        (
            "no closed bar available",
            dataclasses.replace(base, latest_closed_bar_close=None),
            "INVALIDATION_INPUT_UNAVAILABLE",
        ),
    ]
    for label, live, reason in variants:
        store = InMemoryExecutionIntentStore()
        adapter = FakeExecutionAdapter()
        outcome = await _run_plan(adapter, intent_store=store, live_context=live)
        assert (outcome.is_no_trade, outcome.reason_code) == (True, reason), label
        assert "place_entry" not in _reads_only(adapter), label
        assert store.get_entry(approval_id=case_input["approval_id"]) is None, label


async def test_remaining_validity_too_short_refuses() -> None:
    """D-07: 600 s left is not more than the 777 s TEST_ONLY minimum (and the 600 s GTD floor)."""
    case_input = _case_with(now_utc="2026-09-19T10:50:00+00:00")
    adapter = FakeExecutionAdapter(case_input=case_input)
    await _assert_refused_then_placeable(
        label="600 seconds of validity left",
        reason="VALIDITY_TOO_SHORT",
        adapter=adapter,
        expected_calls=PRE_PLACEMENT_READS,
        case_input=case_input,
    )


async def test_hedge_refusal_follows_the_pre_placement_refusals() -> None:
    """A refusal of gate 5e wins over Hedge, and the position mode is then never read."""
    adapter = FakeExecutionAdapter(position_mode="HEDGE")
    adapter.mark_reading = _mark_reading_for(_load_input(), mark_price=Decimal("98.00"))
    outcome = await _run_plan(adapter)
    assert (outcome.is_no_trade, outcome.reason_code) == (True, "MARK_PRICE_CROSSED_STOP")
    assert "get_position_mode" not in _reads_only(adapter)


async def test_hedge_refusal_leaves_the_approval_unconsumed() -> None:
    case_input = _load_input()
    store = InMemoryExecutionIntentStore()
    refused = await _run_plan(FakeExecutionAdapter(position_mode="HEDGE"), intent_store=store)
    assert (refused.is_no_trade, refused.reason_code) == (True, "HEDGE_MODE_UNSUPPORTED")
    assert store.get_entry(approval_id=case_input["approval_id"]) is None
    placed = await _run_plan(FakeExecutionAdapter(), intent_store=store)
    assert (placed.is_no_trade, placed.reason_code) == (False, "OK")


def _order_pairs() -> list[tuple[str, dict[str, Any], str]]:
    """Two gates fail at once: the earlier gate's reason must win. (label, overrides, reason)."""
    import dataclasses

    from tests.support import execution_limits as test_limits

    case_input = _load_input()
    base = _build_live_context(case_input)
    unset = test_limits.test_only_execution_limits(max_mark_price_age_ms=None)
    unset_live = dataclasses.replace(base, execution_limits=unset)

    def risk_no_trade() -> dict[str, Any]:
        risk_kwargs = _build_risk_kwargs(case_input)
        risk_kwargs["account_state"] = type(risk_kwargs["account_state"])(
            equity=Decimal("0.01"), risk_rate=risk_kwargs["account_state"].risk_rate
        )
        return risk_kwargs

    def wrong_side() -> dict[str, Any]:
        risk_kwargs = _build_risk_kwargs(case_input)
        risk_kwargs["candidate_position_side"] = "SHORT"
        return risk_kwargs

    def small_plan_quantity() -> dict[str, Any]:
        risk_kwargs = _build_risk_kwargs(case_input)
        risk_kwargs["trade_plan"] = dataclasses.replace(
            risk_kwargs["trade_plan"], quantity_after_rounding=Decimal("2.414")
        )
        return risk_kwargs

    from src.execution.enablement import LiveEnablementController

    return [
        (
            "binding before limits",
            {"risk_kwargs": wrong_side(), "live_context": unset_live},
            "PLAN_SIDE_MISMATCH",
        ),
        (
            "enablement before limits",
            {
                "enablement": LiveEnablementController(journal=FakeJournal()),
                "live_context": unset_live,
            },
            "DISABLED",
        ),
        (
            "limits before SAFE_MODE",
            {
                "safe_mode_controller": RecordingSafeModeController(in_safe_mode=True),
                "live_context": unset_live,
            },
            "LIMITS_NOT_CONFIGURED",
        ),
        (
            "limits before risk",
            {"risk_kwargs": risk_no_trade(), "live_context": unset_live},
            "LIMITS_NOT_CONFIGURED",
        ),
        (
            "headroom gate before quantity bound",
            {
                "risk_kwargs": small_plan_quantity(),
                "gate_kwargs": _build_gate_kwargs(case_input, open_algo_count=196),
            },
            "EXCHANGE_CONSTRAINT",
        ),
        (
            "quantity bound before the pre-placement reads",
            {"risk_kwargs": small_plan_quantity(), "adapter_mark": Decimal("98.00")},
            "QUANTITY_ABOVE_APPROVED",
        ),
        (
            "plan status before the mark price",
            {"status": "EXPIRED", "adapter_mark": Decimal("98.00")},
            "PLAN_STATUS_INVALID",
        ),
        (
            "invalidation before the symbol check",
            {
                "live_context": dataclasses.replace(base, latest_closed_bar_close=Decimal("97.00")),
                "adapter_orders": [_open_order()],
            },
            "PLAN_INVALIDATED_BEFORE_PLACEMENT",
        ),
        (
            "symbol check before the mark price",
            {"adapter_orders": [_open_order()], "adapter_mark": Decimal("98.00")},
            "SYMBOL_HAS_OPEN_ORDER",
        ),
    ]


async def test_gate_order_is_pinned_by_failing_two_gates_at_once() -> None:
    import dataclasses

    for label, overrides, reason in _order_pairs():
        overrides = dict(overrides)
        adapter = FakeExecutionAdapter()
        if "adapter_mark" in overrides:
            adapter.mark_reading = _mark_reading_for(
                _load_input(), mark_price=overrides.pop("adapter_mark")
            )
        if "adapter_orders" in overrides:
            adapter.open_normal_orders = overrides.pop("adapter_orders")
        if "status" in overrides:
            from src.domain.enums import TradePlanStatus

            risk_kwargs = overrides.get("risk_kwargs") or _build_risk_kwargs(_load_input())
            risk_kwargs["trade_plan"] = dataclasses.replace(
                risk_kwargs["trade_plan"], status=TradePlanStatus[overrides.pop("status")]
            )
            overrides["risk_kwargs"] = risk_kwargs
        outcome = await _run_plan(adapter, **overrides)
        assert (outcome.is_no_trade, outcome.reason_code) == (True, reason), label
        assert "place_entry" not in _reads_only(adapter), label


async def test_pure_refusals_run_before_the_first_read() -> None:
    """Gates 5b-5d are pure: the quantity, geometry and TP1 refusals make zero adapter calls,
    even when the mark price would also cross the stop."""
    for case_input, kwargs in (
        (_case_with(stop_loss_price="99.999", quantity_after_rounding="100"), {}),
        (_case_with(min_quantity="1.500"), {}),
    ):
        adapter = FakeExecutionAdapter(case_input=case_input)
        adapter.mark_reading = _mark_reading_for(case_input, mark_price=Decimal("90.00"))
        outcome = await _run_plan(adapter, case_input=case_input, **kwargs)
        assert outcome.is_no_trade is True
        assert adapter.calls == []
