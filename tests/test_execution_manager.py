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

from src.domain.enums import KillGateState

from tests.support.intent_store_fakes import InMemoryExecutionIntentStore

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
    ) -> None:
        self.calls: list[dict[str, Any]] = []
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


def _live_wiring(**overrides: Any) -> dict[str, Any]:
    """The required live-safety collaborators for `execute_approved_plan`.

    09-REVIEW CR-07/CR-09: SAFE_MODE (and the other live gates) are
    required arguments — tests wire recording doubles explicitly.
    """
    wiring: dict[str, Any] = {
        "safe_mode_controller": RecordingSafeModeController(),
        "journal": FakeJournal(),
        "enablement": _enabled_controller(),
        "gate_kwargs": _build_gate_kwargs(_load_input()),
        # Fresh in-memory store per call: every test keeps its one-call semantics.
        "intent_store": InMemoryExecutionIntentStore(),
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
        plan_hash=case_input["plan_hash"],
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
        request_hash=case_input["plan_hash"],
    )


def _build_callback(case_input: dict[str, Any]) -> Any:
    """Build a Callback payload from the fixture input."""
    from src.approval.binding import Callback

    return Callback(
        raw_token=case_input["raw_token"],
        chat_id=case_input["chat_id"],
        plan_hash=case_input["plan_hash"],
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
        client_order_id="x-33333333333333333333333333333333EN",
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


async def _run_plan(adapter: FakeExecutionAdapter, **overrides: Any) -> Any:
    """Run `execute_approved_plan` on the golden fixture with overrides."""
    from src.execution.manager import execute_approved_plan

    case_input = _load_input()
    kwargs: dict[str, Any] = {
        "callback": _build_callback(case_input),
        "approval": _build_approval(case_input),
        "authorized_chat_id": case_input["chat_id"],
        "expiry_utc": _parse_utc(case_input["expiry_utc"]),
        "approval_strategy_version": case_input["strategy_version"],
        "approval_parameter_set_id": case_input["parameter_set_id"],
        "approval_parameter_set_hash": case_input["parameter_set_hash"],
        "now_utc": _parse_utc(case_input["now_utc"]),
        "adapter": adapter,
        "risk_kwargs": _build_risk_kwargs(case_input),
        **_live_wiring(),
    }
    kwargs.update(overrides)
    return await execute_approved_plan(**kwargs)


def _probe(found: bool) -> Any:
    from src.adapters.binance_usdm import OrderProbe

    return OrderProbe(
        client_order_id="x-33333333333333333333333333333333EN",
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
    adapter = BinanceUsdmAdapter(sdk_client=SimpleNamespace(rest_api=rest))  # type: ignore[arg-type]
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
                "orig_client_order_id": "x-33333333333333333333333333333333EN",
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
    import dataclasses

    case_input = _load_input()
    risk_kwargs = _build_risk_kwargs(case_input)
    risk_kwargs["trade_plan"] = dataclasses.replace(
        risk_kwargs["trade_plan"],
        entry_min_price=Decimal("100.01"),
        entry_max_price=Decimal("100.02"),
    )
    gate_kwargs = _build_gate_kwargs(case_input)
    adapter = FakeExecutionAdapter()

    outcome = await _run_plan(adapter, risk_kwargs=risk_kwargs, gate_kwargs=gate_kwargs)

    assert outcome.is_no_trade is False, outcome
    entry_call = next(c for c in adapter.calls if c["method"] == "place_entry")
    assert entry_call["kwargs"]["price"] == Decimal("100.01")


# --------------------------------------------------------------------------- #
# 09-REVIEW WR-02 — position mode is detected at placement time.
# --------------------------------------------------------------------------- #


async def test_hedge_mode_sends_explicit_position_side_on_entry_and_sl() -> None:
    """WR-02: hedge accounts need positionSide LONG/SHORT everywhere."""
    adapter = FakeExecutionAdapter(position_mode="HEDGE")
    outcome = await _run_plan(adapter)

    assert outcome.is_no_trade is False
    assert adapter.calls[0]["method"] == "get_position_mode"
    entry = next(c for c in adapter.calls if c["method"] == "place_entry")
    sl = next(c for c in adapter.calls if c["method"] == "place_algo_protective")
    assert entry["kwargs"]["position_side"] == "LONG"
    assert sl["kwargs"]["position_side"] == "LONG"


async def test_undeterminable_position_mode_fails_closed_before_any_order() -> None:
    """WR-02: an account-mode query failure never defaults to BOTH."""
    adapter = FakeExecutionAdapter(position_mode="UNKNOWN")
    outcome = await _run_plan(adapter)

    assert outcome.is_no_trade is True
    assert outcome.reason_code == "UNCERTAIN_ACCOUNT_STATE"
    assert [c["method"] for c in adapter.calls] == ["get_position_mode"]


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
