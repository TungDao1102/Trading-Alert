"""Entry-fill to multi-leg filled-qty attach tests (Phase 9, plan 09-04).

Per D-02 + EXECUTION_SPEC sections 5/6: `attach_protectives_to_fill`
folds entry fill events via `fold_fills`, sizes the SL/TP1/TP2 legs via
`size_protectives_to_filled_qty` against the FOLDED filled quantity
only, then places + confirms each leg via `place_algo_protective` with
deterministic `xa-` algo client ids. Confirmation failure on any leg
holds `ENTRY_WITHOUT_PROTECTIVE` immediately — no further legs are
attempted and no rescue placement is ever issued.

The three behaviors pinned here:

  1. Partial-fill sizing to filled qty plus replayed-fill single
     attach: a fill-event list with a replayed duplicate folds to the
     deduplicated filled quantity, and the three protective legs are
     placed exactly once each, sized to that folded quantity.
  2. Unconfirmed-leg divergence with zero rescue placement: an adapter
     that rejects the first (SL) leg yields ENTRY_WITHOUT_PROTECTIVE
     with exactly one `place_algo_protective` call — no retry, no
     TP1/TP2 attempt, no rescue.
  3. Non-live-5 symbol raises ValueError before any adapter call.

The tests load the golden fixture pair
(`tests/fixtures/phase9/attach/{input,expected}.json`).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

PHASE9_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase9"
ATTACH_FIXTURES_DIR = PHASE9_FIXTURES_DIR / "attach"


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _load_input() -> dict[str, Any]:
    return json.loads((ATTACH_FIXTURES_DIR / "input.json").read_text(encoding="utf-8"))


def _load_expected() -> dict[str, Any]:
    return json.loads((ATTACH_FIXTURES_DIR / "expected.json").read_text(encoding="utf-8"))


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


def _build_current_position_view(case_input: dict[str, Any]) -> Any:
    from src.execution.fill_monitor import CurrentPositionView

    cpv = case_input["current_position_view"]
    return CurrentPositionView(
        symbol=cpv["symbol"],
        position_side=cpv["position_side"],
        position_amt=_coerce_decimal(cpv["position_amt"], "position_amt"),
    )


def _build_fill_events(case_input: dict[str, Any]) -> list[Any]:
    """Build `FillEvent` objects from the fixture's fill_events list.

    `fold_fills` only sums `fill_quantity` when it is a `Decimal`
    instance (D-12 boundary discipline) — raw JSON dicts carry string
    values, so the fixture must be converted through `FillEvent`
    (mirrors `tests/test_execution_partials.py:_build_fill_events`).
    """
    from src.execution.fill_monitor import FillEvent

    events: list[Any] = []
    for fe in case_input["fill_events"]:
        events.append(
            FillEvent(
                order_id=fe["order_id"],
                exchange_trade_id=fe["exchange_trade_id"],
                symbol=fe["symbol"],
                side=fe["side"],
                position_side=fe["position_side"],
                fill_price=_coerce_decimal(fe["fill_price"], "fill_price"),
                fill_quantity=_coerce_decimal(fe["fill_quantity"], "fill_quantity"),
                fill_time_utc=_parse_utc(fe["fill_time_utc"]),
            )
        )
    return events


def _build_protective_template(case_input: dict[str, Any]) -> Any:
    from src.execution.placement import ProtectiveTemplate

    pt = case_input["protective_template"]
    return ProtectiveTemplate(
        stop_loss_trigger_price=_coerce_decimal(
            pt["stop_loss_trigger_price"], "stop_loss_trigger_price"
        ),
        tp1_trigger_price=_coerce_decimal(pt["tp1_trigger_price"], "tp1_trigger_price"),
        tp2_trigger_price=_coerce_decimal(pt["tp2_trigger_price"], "tp2_trigger_price"),
        tp1_quantity_fraction=_coerce_decimal(
            pt["tp1_quantity_fraction"], "tp1_quantity_fraction"
        ),
    )


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


# --------------------------------------------------------------------------- #
# FakeExecutionAdapter — records every place_algo_protective call.
# --------------------------------------------------------------------------- #


class FakeExecutionAdapter:
    """In-memory adapter recording `place_algo_protective` calls.

    `reject_client_algo_ids` optionally names algo client ids whose
    call should return a rejected-shaped response (simulating an
    unconfirmed leg) instead of the default accepted response.
    """

    def __init__(self, *, reject_client_algo_ids: frozenset[str] = frozenset()) -> None:
        self.calls: list[dict[str, Any]] = []
        self._reject_client_algo_ids = reject_client_algo_ids

    async def place_algo_protective(self, **kwargs: Any) -> Any:
        # Contract guard (09-REVIEW CR-01): the manager's kwargs must bind
        # against the REAL adapter signature, not just this `**kwargs` fake.
        import inspect

        from src.adapters.binance_usdm import BinanceUsdmAdapter

        inspect.signature(BinanceUsdmAdapter.place_algo_protective).bind(None, **kwargs)
        self.calls.append({"method": "place_algo_protective", "kwargs": dict(kwargs)})
        if kwargs.get("client_algo_id") in self._reject_client_algo_ids:
            return {"algo_status": "REJECTED"}
        return {"algo_id": f"algo_{kwargs.get('client_algo_id')}", "algo_status": "NEW"}


# --------------------------------------------------------------------------- #
# Beh. 1 — partial-fill sizing to filled qty plus replayed-fill single attach.
# --------------------------------------------------------------------------- #


def test_partial_fill_replayed_fills_fold_and_attach_once() -> None:
    """Beh. 1: a fill-event list with a replayed duplicate folds to the
    deduplicated filled quantity, and the three protective legs are
    placed exactly once each, sized to that folded quantity.
    """
    from src.execution.manager import attach_protectives_to_fill

    case_input = _load_input()
    expected = _load_expected()

    adapter = FakeExecutionAdapter()
    current_view = _build_current_position_view(case_input)
    protective_template = _build_protective_template(case_input)
    constraint_snapshot = _build_constraint_snapshot(case_input)

    outcome = asyncio.run(
        attach_protectives_to_fill(
            fill_events=_build_fill_events(case_input),
            current_position_view=current_view,
            has_protective=False,
            protective_template=protective_template,
            constraint_snapshot=constraint_snapshot,
            position_mode=case_input["position_mode"],
            candidate_position_side=case_input["candidate_position_side"],
            plan_hash=case_input["plan_hash"],
            adapter=adapter,
            now_utc=_parse_utc(case_input["now_utc"]),
        )
    )

    assert outcome.is_no_trade is False, f"expected PASS, got NO_TRADE: {outcome.reason_code}"
    assert outcome.reason_code == expected["reason_code"]
    assert outcome.sized.tp1_leg["quantity"] == _coerce_decimal(
        expected["tp1_leg"]["quantity"], "tp1_quantity"
    )

    # Exactly 3 place_algo_protective calls (SL, TP1, TP2) — the
    # replayed fill event did NOT cause a fourth call or a doubled
    # filled quantity.
    method_sequence = [c["method"] for c in adapter.calls]
    assert method_sequence == expected["method_sequence"], (
        f"adapter call sequence mismatch: got {method_sequence}, "
        f"expected {expected['method_sequence']}"
    )

    sl_call, tp1_call, tp2_call = adapter.calls
    assert sl_call["kwargs"]["client_algo_id"] == expected["sl_algo_client_id"]
    assert sl_call["kwargs"]["trigger_price"] == _coerce_decimal(
        expected["sl_leg"]["trigger_price"], "sl_trigger_price"
    )
    assert sl_call["kwargs"]["quantity"] is None

    assert tp1_call["kwargs"]["client_algo_id"] == expected["tp1_algo_client_id"]
    assert tp1_call["kwargs"]["quantity"] == _coerce_decimal(
        expected["tp1_leg"]["quantity"], "tp1_quantity"
    )
    assert tp1_call["kwargs"]["reduce_only"] is True

    assert tp2_call["kwargs"]["client_algo_id"] == expected["tp2_algo_client_id"]
    assert tp2_call["kwargs"]["quantity"] is None

    assert outcome.placed_legs == ("STOP_LOSS", "TAKE_PROFIT_1", "TAKE_PROFIT_2")


# --------------------------------------------------------------------------- #
# Beh. 2 — unconfirmed-leg divergence with zero rescue placement.
# --------------------------------------------------------------------------- #


def test_unconfirmed_sl_leg_yields_entry_without_protective_with_zero_rescue() -> None:
    """Beh. 2: an adapter that rejects the SL leg yields
    ENTRY_WITHOUT_PROTECTIVE with exactly one `place_algo_protective`
    call — no retry, no TP1/TP2 attempt, no rescue placement.
    """
    from src.execution.manager import attach_protectives_to_fill

    case_input = _load_input()
    expected = _load_expected()

    adapter = FakeExecutionAdapter(
        reject_client_algo_ids=frozenset({expected["sl_algo_client_id"]})
    )
    current_view = _build_current_position_view(case_input)
    protective_template = _build_protective_template(case_input)
    constraint_snapshot = _build_constraint_snapshot(case_input)

    class _RecordingSafeModeController:
        def __init__(self) -> None:
            self.entered_reasons: list[str] = []

        def enter_safe_mode(self, *, reason: str, now_utc: Any = None) -> None:
            self.entered_reasons.append(reason)

    safe_mode_controller = _RecordingSafeModeController()

    outcome = asyncio.run(
        attach_protectives_to_fill(
            fill_events=_build_fill_events(case_input),
            current_position_view=current_view,
            has_protective=False,
            protective_template=protective_template,
            constraint_snapshot=constraint_snapshot,
            position_mode=case_input["position_mode"],
            candidate_position_side=case_input["candidate_position_side"],
            plan_hash=case_input["plan_hash"],
            adapter=adapter,
            now_utc=_parse_utc(case_input["now_utc"]),
            safe_mode_controller=safe_mode_controller,
        )
    )

    assert outcome.is_no_trade is True
    assert outcome.reason_code == "ENTRY_WITHOUT_PROTECTIVE"
    assert outcome.placed_legs == ()

    # Exactly one place_algo_protective call (the failing SL leg) —
    # zero rescue attempts, zero TP1/TP2 attempts.
    assert len(adapter.calls) == 1, (
        f"expected exactly 1 adapter call (no rescue), got {len(adapter.calls)}: {adapter.calls}"
    )
    assert adapter.calls[0]["kwargs"]["client_algo_id"] == expected["sl_algo_client_id"]

    # SAFE_MODE composition was triggered on the divergence.
    assert safe_mode_controller.entered_reasons == ["ENTRY_WITHOUT_PROTECTIVE"]


# --------------------------------------------------------------------------- #
# Beh. 3 — non-live-5 symbol raises ValueError before any adapter call.
# --------------------------------------------------------------------------- #


def test_non_live5_symbol_raises_before_any_adapter_call() -> None:
    """Beh. 3: a non-live-5 symbol raises ValueError before any
    adapter call.
    """
    from src.execution.manager import attach_protectives_to_fill

    case_input = _load_input()
    adapter = FakeExecutionAdapter()
    current_view = _build_current_position_view(case_input)
    protective_template = _build_protective_template(case_input)

    # Build a constraint snapshot for a non-live-5 symbol (DOGEUSDT).
    from src.risk.types import ConstraintSnapshot

    non_live5_snapshot = ConstraintSnapshot(
        symbol="DOGEUSDT",
        price_tick_size=Decimal("0.00001"),
        quantity_step_size=Decimal("1"),
        min_quantity=Decimal("1"),
        min_notional=Decimal("5.00"),
        metadata_observed_at_utc=_parse_utc(case_input["constraint_snapshot"]["metadata_observed_at_utc"]),
    )

    with pytest.raises(ValueError, match="live-5"):
        asyncio.run(
            attach_protectives_to_fill(
                fill_events=_build_fill_events(case_input),
                current_position_view=current_view,
                has_protective=False,
                protective_template=protective_template,
                constraint_snapshot=non_live5_snapshot,
                position_mode=case_input["position_mode"],
                candidate_position_side=case_input["candidate_position_side"],
                plan_hash=case_input["plan_hash"],
                adapter=adapter,
                now_utc=_parse_utc(case_input["now_utc"]),
            )
        )

    assert adapter.calls == []


# --------------------------------------------------------------------------- #
# Beh. 4 — purity: no float() and no Binance SDK imports in manager.py.
# --------------------------------------------------------------------------- #


def test_manager_module_has_no_float_in_new_attach_code() -> None:
    """Beh. 4: src/execution/manager.py does not use float() for
    placement math (Decimal-only per D-05), even after the 09-04
    additions.
    """
    import re

    module_path = Path("src/execution/manager.py")
    source = module_path.read_text(encoding="utf-8")
    match = re.search(r"\bfloat\s*\(", source)
    assert match is None, f"float() found in {module_path}: {match.group(0)!r}"


def test_manager_module_does_not_import_binance_sdk() -> None:
    """Beh. 5: src/execution/manager.py does not import the Binance SDK."""
    import re

    module_path = Path("src/execution/manager.py")
    source = module_path.read_text(encoding="utf-8")
    forbidden_patterns = [r"\bimport\s+binance_sdk\b", r"\bfrom\s+binance_sdk\b"]
    for pattern in forbidden_patterns:
        match = re.search(pattern, source)
        assert match is None, (
            f"forbidden import in {module_path}: pattern={pattern!r}, match={match.group(0)!r}"
        )
