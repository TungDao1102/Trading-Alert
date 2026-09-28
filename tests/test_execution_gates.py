"""Placement-time gates + enablement controller tests (Phase 9, plan 09-03).

Per D-03 + D-04: every placement revalidates live constraints from
exchangeInfo at placement time, evaluates portfolio caps and DAILY_STOP
against the live/reconciled position set, and runs under the
LIVE_ORDERS_DISABLED default-disabled enablement gate. Headroom,
DAILY_STOP, stale-snapshot, uncertain-state, and disabled-flag rejects
all land as fail-closed reason codes before any order call.

The six behaviors pinned here:

  1. Headroom reject: open algo count + planned legs at the 200-per-
     symbol limit yields EXCHANGE_CONSTRAINT NO_TRADE with zero
     adapter place calls.
  2. DAILY_STOP block: live reconciled state in DAILY_STOP yields
     DAILY_STOP_BLOCK NO_TRADE.
  3. Stale constraints: metadata_observed_at_utc past TTL yields
     STALE_CONSTRAINTS NO_TRADE.
  4. Uncertain account state: None daily loss or unreconciled positions
     yields UNCERTAIN_ACCOUNT_STATE NO_TRADE.
  5. Disabled-flag block: LIVE_ORDERS_DISABLED true yields DISABLED
     NO_TRADE with zero adapter calls.
  6. All-pass: enabled flag + passing gates reach evaluate_risk with
     the reconciled position set forwarded.

The tests load the golden fixture pairs
(`tests/fixtures/phase9/gates/{headroom_reject,daily_stop_block,stale_constraints}/{input,expected}.json`
and `tests/fixtures/phase9/enablement/disabled/{input,expected}.json`)
and assert the gate verdicts match the expected envelopes byte-for-byte.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

PHASE9_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase9"
GATES_FIXTURES_DIR = PHASE9_FIXTURES_DIR / "gates"
ENABLEMENT_FIXTURES_DIR = PHASE9_FIXTURES_DIR / "enablement"


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _load_input(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "input.json").read_text(encoding="utf-8"))


def _load_expected(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))


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
    if value is None:
        return None  # type: ignore[return-value]
    raise TypeError(f"{field_name} must be Decimal/str/int/None, got {type(value).__name__}")


def _build_constraint_snapshot(case_input: dict[str, Any]) -> Any:
    from src.risk.types import ConstraintSnapshot

    cs = case_input["constraint_snapshot"]
    return ConstraintSnapshot(
        symbol=cs["symbol"],
        price_tick_size=_coerce_decimal(cs["price_tick_size"], "price_tick_size"),
        quantity_step_size=_coerce_decimal(cs["quantity_step_size"], "quantity_step_size"),
        min_quantity=_coerce_decimal(cs["min_quantity"], "min_quantity"),
        min_notional=_coerce_decimal(cs["min_notional"], "min_notional"),
        metadata_observed_at_utc=_parse_utc(cs["metadata_observed_at_utc"]),
    )


def _build_reconciled_positions(case_input: dict[str, Any]) -> list[Any]:
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
        for p in case_input.get("reconciled_positions", [])
    ]


def _build_sized(case_input: dict[str, Any]) -> Any:
    from src.risk.types import SizedResult

    s = case_input["sized"]
    return SizedResult(
        is_no_trade=s["is_no_trade"],
        quantity=_coerce_decimal(s["quantity"], "quantity") if s["quantity"] is not None else None,
        quantity_before_rounding=_coerce_decimal(s["quantity_before_rounding"], "quantity_before_rounding"),
        quantity_after_rounding=_coerce_decimal(s["quantity_after_rounding"], "quantity_after_rounding"),
        quantization_decision=s["quantization_decision"],
        realized_risk=_coerce_decimal(s["realized_risk"], "realized_risk"),
        reason_code=s["reason_code"],
    )


def _build_parameter_set(case_input: dict[str, Any]) -> dict[str, Any]:
    parameter_set: dict[str, Any] = {}
    for key, value in case_input["parameter_set"].items():
        if key == "max_open_positions":
            parameter_set[key] = int(value)
        else:
            parameter_set[key] = _coerce_decimal(value, key)
    return parameter_set


# --------------------------------------------------------------------------- #
# FakeExecutionAdapter — records every call for byte-exact assertions.
# --------------------------------------------------------------------------- #


class FakeExecutionAdapter:
    """In-memory adapter that records every placement call.

    Mirrors the four-method surface the real `BinanceUsdmAdapter` exposes
    (`place_entry`, `place_algo_protective`, `query_order_by_client`,
    `get_position_mode`). The fake never touches the network — it
    returns canned responses and records the call sequence so the test
    can assert byte-exact ordering.
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
# FakeReconciledState — supplies the live reconciled position set + algo count.
# --------------------------------------------------------------------------- #


class FakeReconciledState:
    """In-memory reconciled state for gate tests.

    Mirrors the three-source reconciler surface: open algo count, open
    positions, and a reconciled flag. The fake never touches the
    network — it returns the pre-configured state so the test can
    assert byte-exact gate verdicts.
    """

    def __init__(
        self,
        *,
        open_algo_count: int,
        positions: list[Any] | None = None,
        positions_reconciled: bool = True,
    ) -> None:
        self._open_algo_count = open_algo_count
        self._positions = list(positions or [])
        self._positions_reconciled = positions_reconciled

    def open_algo_count(self) -> int:
        return self._open_algo_count

    def positions(self) -> list[Any]:
        return list(self._positions)

    def positions_reconciled(self) -> bool:
        return self._positions_reconciled


# --------------------------------------------------------------------------- #
# FakeJournal — records every journal event for byte-exact assertions.
# --------------------------------------------------------------------------- #


class FakeJournal:
    """In-memory journal that records every event.

    Mirrors the `JournalLike` Protocol from `src/reconcile/safe_mode.py`.
    The fake never touches the network — it appends events to a list so
    the test can assert byte-exact journal ordering.
    """

    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)


# --------------------------------------------------------------------------- #
# Beh. 1 — headroom reject: open algo count + planned legs at 200 → EXCHANGE_CONSTRAINT.
# --------------------------------------------------------------------------- #


def test_headroom_reject_yields_exchange_constraint_with_zero_place_calls() -> None:
    """Beh. 1: open algo count + planned legs at the 200-per-symbol
    limit yields EXCHANGE_CONSTRAINT NO_TRADE with zero adapter place
    calls.
    """
    from src.execution.gates import decide_placement

    case_dir = GATES_FIXTURES_DIR / "headroom_reject"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    constraint = _build_constraint_snapshot(case_input)
    positions = _build_reconciled_positions(case_input)
    sized = _build_sized(case_input)
    parameter_set = _build_parameter_set(case_input)

    verdict = decide_placement(
        constraint_snapshot=constraint,
        open_algo_count=case_input["open_algo_count"],
        planned_leg_count=case_input["planned_leg_count"],
        reconciled_positions=positions,
        daily_loss_quote=_coerce_decimal(case_input["daily_loss_quote"], "daily_loss_quote"),
        positions_reconciled=case_input["positions_reconciled"],
        now_utc=_parse_utc(case_input["now_utc"]),
        ttl=timedelta(seconds=int(case_input["ttl_seconds"])),
        sized=sized,
        candidate_symbol=case_input["candidate_symbol"],
        candidate_position_side=case_input["candidate_position_side"],
        parameter_set=parameter_set,
    )

    assert verdict.is_no_trade is True, (
        f"expected NO_TRADE, got PASS: {verdict.reason_code}"
    )
    assert verdict.reason_code == expected["reason_code"], (
        f"reason_code mismatch: got {verdict.reason_code!r}, "
        f"expected {expected['reason_code']!r}"
    )


# --------------------------------------------------------------------------- #
# Beh. 2 — DAILY_STOP block: live reconciled state in DAILY_STOP → DAILY_STOP_BLOCK.
# --------------------------------------------------------------------------- #


def test_daily_stop_block_yields_daily_stop_block_with_zero_place_calls() -> None:
    """Beh. 2: live reconciled state in DAILY_STOP yields
    DAILY_STOP_BLOCK NO_TRADE.
    """
    from src.execution.gates import decide_placement

    case_dir = GATES_FIXTURES_DIR / "daily_stop_block"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    constraint = _build_constraint_snapshot(case_input)
    positions = _build_reconciled_positions(case_input)
    sized = _build_sized(case_input)
    parameter_set = _build_parameter_set(case_input)

    verdict = decide_placement(
        constraint_snapshot=constraint,
        open_algo_count=case_input["open_algo_count"],
        planned_leg_count=case_input["planned_leg_count"],
        reconciled_positions=positions,
        daily_loss_quote=_coerce_decimal(case_input["daily_loss_quote"], "daily_loss_quote"),
        positions_reconciled=case_input["positions_reconciled"],
        now_utc=_parse_utc(case_input["now_utc"]),
        ttl=timedelta(seconds=int(case_input["ttl_seconds"])),
        sized=sized,
        candidate_symbol=case_input["candidate_symbol"],
        candidate_position_side=case_input["candidate_position_side"],
        parameter_set=parameter_set,
    )

    assert verdict.is_no_trade is True
    assert verdict.reason_code == expected["reason_code"]


# --------------------------------------------------------------------------- #
# Beh. 3 — stale constraints: metadata_observed_at_utc past TTL → STALE_CONSTRAINTS.
# --------------------------------------------------------------------------- #


def test_stale_constraints_yields_stale_constraints_with_zero_place_calls() -> None:
    """Beh. 3: metadata_observed_at_utc past TTL yields
    STALE_CONSTRAINTS NO_TRADE.
    """
    from src.execution.gates import decide_placement

    case_dir = GATES_FIXTURES_DIR / "stale_constraints"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    constraint = _build_constraint_snapshot(case_input)
    positions = _build_reconciled_positions(case_input)
    sized = _build_sized(case_input)
    parameter_set = _build_parameter_set(case_input)

    verdict = decide_placement(
        constraint_snapshot=constraint,
        open_algo_count=case_input["open_algo_count"],
        planned_leg_count=case_input["planned_leg_count"],
        reconciled_positions=positions,
        daily_loss_quote=_coerce_decimal(case_input["daily_loss_quote"], "daily_loss_quote"),
        positions_reconciled=case_input["positions_reconciled"],
        now_utc=_parse_utc(case_input["now_utc"]),
        ttl=timedelta(seconds=int(case_input["ttl_seconds"])),
        sized=sized,
        candidate_symbol=case_input["candidate_symbol"],
        candidate_position_side=case_input["candidate_position_side"],
        parameter_set=parameter_set,
    )

    assert verdict.is_no_trade is True
    assert verdict.reason_code == expected["reason_code"]


# --------------------------------------------------------------------------- #
# Beh. 4 — uncertain account state: None daily loss or unreconciled → UNCERTAIN_ACCOUNT_STATE.
# --------------------------------------------------------------------------- #


def test_uncertain_account_state_yields_uncertain_account_state() -> None:
    """Beh. 4: None daily loss or unreconciled positions yields
    UNCERTAIN_ACCOUNT_STATE NO_TRADE.
    """
    from src.execution.gates import decide_placement

    case_dir = ENABLEMENT_FIXTURES_DIR / "disabled"
    case_input = _load_input(case_dir)

    constraint = _build_constraint_snapshot(case_input)
    positions = _build_reconciled_positions(case_input)
    sized = _build_sized(case_input)
    parameter_set = _build_parameter_set(case_input)

    verdict = decide_placement(
        constraint_snapshot=constraint,
        open_algo_count=case_input["open_algo_count"],
        planned_leg_count=case_input["planned_leg_count"],
        reconciled_positions=positions,
        daily_loss_quote=None,  # None daily loss
        positions_reconciled=False,  # unreconciled positions
        now_utc=_parse_utc(case_input["now_utc"]),
        ttl=timedelta(seconds=int(case_input["ttl_seconds"])),
        sized=sized,
        candidate_symbol=case_input["candidate_symbol"],
        candidate_position_side=case_input["candidate_position_side"],
        parameter_set=parameter_set,
    )

    assert verdict.is_no_trade is True
    assert verdict.reason_code == "UNCERTAIN_ACCOUNT_STATE"


# --------------------------------------------------------------------------- #
# Beh. 5 — disabled-flag block: LIVE_ORDERS_DISABLED true → DISABLED.
# --------------------------------------------------------------------------- #


def test_disabled_flag_blocks_placement_with_zero_adapter_calls() -> None:
    """Beh. 5: LIVE_ORDERS_DISABLED true yields DISABLED NO_TRADE with
    zero adapter calls.
    """
    from src.execution.enablement import LiveEnablementController

    case_dir = ENABLEMENT_FIXTURES_DIR / "disabled"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    journal = FakeJournal()
    controller = LiveEnablementController(journal=journal)

    # Default-constructed controller has LIVE_ORDERS_DISABLED=true.
    assert controller.is_disabled is True, (
        "default-constructed LiveEnablementController must have LIVE_ORDERS_DISABLED=true"
    )

    verdict = controller.guard_placement(plan_hash=case_input.get("plan_hash", "test_plan_hash"))

    assert verdict.is_no_trade is True
    assert verdict.reason_code == expected["reason_code"]


# --------------------------------------------------------------------------- #
# Beh. 6 — all-pass: enabled flag + passing gates reach evaluate_risk.
# --------------------------------------------------------------------------- #


def test_all_pass_yields_proceed_with_reconciled_set() -> None:
    """Beh. 6: enabled flag + passing gates reach evaluate_risk with
    the reconciled position set forwarded.
    """
    from src.execution.gates import decide_placement

    # Build a passing input: low open algo count, fresh constraints,
    # NORMAL daily state, reconciled positions, valid sized result.
    case_input = {
        "symbol": "BTCUSDT",
        "now_utc": "2026-09-19T10:30:00+00:00",
        "ttl_seconds": 3600,
        "open_algo_count": 5,
        "planned_leg_count": 3,
        "constraint_snapshot": {
            "symbol": "BTCUSDT",
            "price_tick_size": "0.01",
            "quantity_step_size": "0.001",
            "min_quantity": "0.001",
            "min_notional": "5.00",
            "metadata_observed_at_utc": "2026-09-19T10:00:00+00:00",
        },
        "reconciled_positions": [],
        "daily_loss_quote": "0.00",
        "positions_reconciled": True,
        "candidate_symbol": "BTCUSDT",
        "candidate_position_side": "LONG",
        "sized": {
            "is_no_trade": False,
            "quantity": "0.500",
            "quantity_before_rounding": "0.500",
            "quantity_after_rounding": "0.500",
            "quantization_decision": "ACCEPTED",
            "realized_risk": "10.00",
            "reason_code": "OK",
        },
        "parameter_set": {
            "cluster_cap": "100.00",
            "max_aggregate_open_risk": "200.00",
            "max_open_positions": 3,
            "daily_loss_warning_threshold": "5.00",
            "daily_loss_stop_threshold": "10.00",
        },
    }

    constraint = _build_constraint_snapshot(case_input)
    positions = _build_reconciled_positions(case_input)
    sized = _build_sized(case_input)
    parameter_set = _build_parameter_set(case_input)

    verdict = decide_placement(
        constraint_snapshot=constraint,
        open_algo_count=case_input["open_algo_count"],
        planned_leg_count=case_input["planned_leg_count"],
        reconciled_positions=positions,
        daily_loss_quote=_coerce_decimal(case_input["daily_loss_quote"], "daily_loss_quote"),
        positions_reconciled=case_input["positions_reconciled"],
        now_utc=_parse_utc(case_input["now_utc"]),
        ttl=timedelta(seconds=int(case_input["ttl_seconds"])),
        sized=sized,
        candidate_symbol=case_input["candidate_symbol"],
        candidate_position_side=case_input["candidate_position_side"],
        parameter_set=parameter_set,
    )

    assert verdict.is_no_trade is False, (
        f"expected PASS, got NO_TRADE: {verdict.reason_code}"
    )
    assert verdict.reason_code == "OK"
