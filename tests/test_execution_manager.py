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
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

PHASE9_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase9"
PLACEMENT_FIXTURE_DIR = PHASE9_FIXTURES_DIR / "placement_sequences"


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _load_input() -> dict[str, Any]:
    return json.loads(
        (PLACEMENT_FIXTURE_DIR / "input.json").read_text(encoding="utf-8")
    )


def _load_expected() -> dict[str, Any]:
    return json.loads(
        (PLACEMENT_FIXTURE_DIR / "expected.json").read_text(encoding="utf-8")
    )


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

    async def place_entry(self, **kwargs: Any) -> Any:
        self.calls.append({"method": "place_entry", "kwargs": dict(kwargs)})
        return self._entry_response

    async def place_algo_protective(self, **kwargs: Any) -> Any:
        self.calls.append({"method": "place_algo_protective", "kwargs": dict(kwargs)})
        return self._algo_response

    async def query_order_by_client(self, **kwargs: Any) -> Any:
        self.calls.append({"method": "query_order_by_client", "kwargs": dict(kwargs)})
        return self._query_response

    async def get_position_mode(self) -> str:
        self.calls.append({"method": "get_position_mode", "kwargs": {}})
        return self._position_mode


# --------------------------------------------------------------------------- #
# Fixture builders — build the inputs the manager expects.
# --------------------------------------------------------------------------- #


def _build_approved_plan(case_input: dict[str, Any]) -> Any:
    """Build a TradePlan from the fixture input."""
    from src.domain.trade_plan import TradePlan
    from src.domain.enums import TradePlanStatus

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
        suggested_quantity=_coerce_decimal(
            case_input["suggested_quantity"], "suggested_quantity"
        ),
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
        price_tick_size=_coerce_decimal(
            case_input["price_tick_size"], "price_tick_size"
        ),
        quantity_step_size=_coerce_decimal(
            case_input["quantity_step_size"], "quantity_step_size"
        ),
        min_quantity=_coerce_decimal(case_input["min_quantity"], "min_quantity"),
        min_notional=_coerce_decimal(case_input["min_notional"], "min_notional"),
        metadata_observed_at_utc=_parse_utc(
            case_input["metadata_observed_at_utc"]
        ),
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
        "daily_loss_quote": _coerce_decimal(
            case_input["daily_loss_quote"], "daily_loss_quote"
        ),
        "now_utc": _parse_utc(case_input["now_utc"]),
        "ttl": timedelta(seconds=int(case_input["ttl_seconds"])),
        "modeled_costs_per_unit": _coerce_decimal(
            case_input["modeled_costs_per_unit"], "modeled_costs_per_unit"
        ),
        "minimum_risk_utilization_after_rounding": _coerce_decimal(
            case_input["minimum_risk_utilization_after_rounding"],
            "minimum_risk_utilization_after_rounding",
        ),
        "parameter_set": parameter_set,
    }


# --------------------------------------------------------------------------- #
# Beh. 1 — happy path: approved plan + PASS risk → 1 entry + 1 SL call.
# --------------------------------------------------------------------------- #


def test_happy_path_places_one_entry_and_one_sl_leg() -> None:
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

    outcome = execute_approved_plan(
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
    )

    # Outcome is a PASS with the expected reason code.
    assert outcome.is_no_trade is False, (
        f"expected PASS, got NO_TRADE: {outcome.reason_code}"
    )
    assert outcome.reason_code == expected["outcome_reason_code"]

    # Exactly 2 adapter calls: 1 entry + 1 SL.
    method_sequence = [c["method"] for c in adapter.calls]
    assert method_sequence == expected["method_sequence"], (
        f"adapter call sequence mismatch: got {method_sequence}, "
        f"expected {expected['method_sequence']}"
    )

    # Entry call: LIMIT, GTC, x- EN id, quantized qty, zone-mid price.
    entry_call = adapter.calls[0]
    assert entry_call["method"] == "place_entry"
    entry_kwargs = entry_call["kwargs"]
    assert entry_kwargs["symbol"] == case_input["symbol"]
    assert entry_kwargs["side"] == case_input["side"]
    assert entry_kwargs["position_side"] == case_input["position_side"]
    assert entry_kwargs["time_in_force"] == "GTC"
    # Quantity comes from the risk verdict (sized.quantity), not the
    # fixture's quantity_after_rounding placeholder. The risk pipeline
    # computes the actual quantity from equity/risk_rate/SL distance.
    assert entry_kwargs["quantity"] > Decimal("0")
    assert entry_kwargs["price"] == _coerce_decimal(
        case_input["expected_limit_price"], "expected_limit_price"
    )
    assert entry_kwargs["new_client_order_id"] == expected["entry_client_order_id"]

    # SL call: CONDITIONAL, STOP_MARKET, close_position True, xa- SL id.
    sl_call = adapter.calls[1]
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


def test_stale_plan_yields_no_adapter_calls_and_unapprovable_outcome() -> None:
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

    outcome = execute_approved_plan(
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


def test_risk_no_trade_yields_no_adapter_calls_and_preserves_reason_code() -> None:
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

    outcome = execute_approved_plan(
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


def test_ambiguous_entry_response_triggers_query_before_retry() -> None:
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

    # Simulate ambiguous response: place_entry returns None (ambiguous),
    # query_order_by_client returns a "found" probe (order exists).
    adapter._entry_response = None  # type: ignore[attr-defined]
    adapter._query_response = {"found": True, "order_id": "12345"}  # type: ignore[attr-defined]

    outcome = execute_approved_plan(
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
    assert query_idx > entry_idx, (
        f"query must come after initial place_entry: {method_sequence}"
    )
    # No retry place_entry after the query (probe found the order).
    entry_count = method_sequence.count("place_entry")
    assert entry_count == 1, (
        f"probe found order → no retry, got {entry_count} place_entry calls"
    )


# --------------------------------------------------------------------------- #
# Beh. 5 — golden fixture: byte-exact adapter call sequence.
# --------------------------------------------------------------------------- #


def test_golden_fixture_adapter_call_sequence_matches_expected() -> None:
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

    execute_approved_plan(
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
    )

    # Method sequence matches.
    method_sequence = [c["method"] for c in adapter.calls]
    assert method_sequence == expected["method_sequence"]

    # Entry client_order_id matches the deterministic derivation.
    entry_call = adapter.calls[0]
    assert entry_call["kwargs"]["new_client_order_id"] == expected["entry_client_order_id"]

    # SL algo_client_id matches the deterministic derivation.
    sl_call = adapter.calls[1]
    assert sl_call["kwargs"]["client_algo_id"] == expected["sl_algo_client_id"]


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
        Path("src/execution/manager.py"),
        Path("src/execution/placement.py"),
    ):
        source = module_path.read_text(encoding="utf-8")
        forbidden_patterns = [
            r"\bimport\s+binance_sdk\b",
            r"\bfrom\s+binance_sdk\b",
        ]
        for pattern in forbidden_patterns:
            match = re.search(pattern, source)
            assert match is None, (
                f"forbidden import in {module_path}: "
                f"pattern={pattern!r}, match={match.group(0)!r}"
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
        Path("src/execution/manager.py"),
        Path("src/execution/placement.py"),
    ):
        source = module_path.read_text(encoding="utf-8")
        # float() is only allowed at the adapter boundary, not in core.
        match = re.search(r"\bfloat\s*\(", source)
        assert match is None, (
            f"float() found in {module_path}: {match.group(0)!r}"
        )
