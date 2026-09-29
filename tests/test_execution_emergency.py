"""Expiry / protective-cancel / emergency-close tests (09-REVIEW CR-10).

Every fake adapter call here is bound against the REAL
`BinanceUsdmAdapter` method signature, so a manager call to a method
the real adapter does not have (the original `cancel_order` bug) fails
the test instead of passing against a `**kwargs` fake.
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from src.adapters.binance_usdm import BinanceUsdmAdapter
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id

NOW_UTC = datetime(2026, 9, 29, 10, 30, tzinfo=UTC)
PLAN_HASH = "3333333333333333333333333333333333333333333333333333333333333333"
SYMBOL = "BTCUSDT"


class FakeJournal:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)

    def phases(self) -> list[tuple[str, str]]:
        return [(e.entity_id, json.loads(e.payload_json)["phase"]) for e in self.events]


class ContractCancelAdapter:
    """Records cancel calls; binds kwargs against the REAL adapter."""

    def __init__(self, *, fail_ids: frozenset[str] = frozenset()) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._fail_ids = fail_ids

    def _record(self, method: str, kwargs: dict[str, Any]) -> None:
        # AttributeError here if the manager calls a method the real
        # adapter does not have; TypeError on a kwarg mismatch.
        inspect.signature(getattr(BinanceUsdmAdapter, method)).bind(None, **kwargs)
        self.calls.append((method, kwargs))

    async def cancel_normal_order(self, **kwargs: Any) -> None:
        self._record("cancel_normal_order", kwargs)
        if kwargs["orig_client_order_id"] in self._fail_ids:
            raise RuntimeError("simulated network failure")

    async def cancel_algo_order(self, **kwargs: Any) -> None:
        self._record("cancel_algo_order", kwargs)
        if kwargs["client_algo_id"] in self._fail_ids:
            raise RuntimeError("simulated rate limit")


class RecordingEnablement:
    def __init__(self, order: list[str]) -> None:
        self._order = order
        self.disabled = False

    def disable(self, *, operator_id: str, now_utc: datetime) -> None:
        self._order.append("disable")
        self.disabled = True


class RecordingSafeMode:
    def __init__(self, order: list[str]) -> None:
        self._order = order
        self.reasons: list[str] = []

    def enter_safe_mode(self, *, reason: str, now_utc: Any = None) -> None:
        self._order.append("safe_mode")
        self.reasons.append(reason)


ENTRY_ID = derive_client_order_id(plan_hash=PLAN_HASH, role="ENTRY")
SL_ID = derive_algo_client_id(plan_hash=PLAN_HASH, role="STOP_LOSS")
TP1_ID = derive_algo_client_id(plan_hash=PLAN_HASH, role="TAKE_PROFIT_1")
TP2_ID = derive_algo_client_id(plan_hash=PLAN_HASH, role="TAKE_PROFIT_2")


async def test_expire_pending_entry_uses_real_cancel_normal_order_surface() -> None:
    from src.execution.manager import expire_pending_entry

    adapter = ContractCancelAdapter()
    journal = FakeJournal()
    await expire_pending_entry(
        plan_hash=PLAN_HASH,
        symbol=SYMBOL,
        adapter=adapter,  # type: ignore[arg-type]
        journal=journal,
        now_utc=NOW_UTC,
        trigger_reason="expiry_time",
    )
    assert adapter.calls == [
        ("cancel_normal_order", {"symbol": SYMBOL, "orig_client_order_id": ENTRY_ID})
    ]
    assert journal.phases() == [(ENTRY_ID, "pre_cancel"), (ENTRY_ID, "post_cancel")]


async def test_expire_pending_entry_failure_is_journaled_and_reraised() -> None:
    from src.execution.manager import expire_pending_entry

    adapter = ContractCancelAdapter(fail_ids=frozenset({ENTRY_ID}))
    journal = FakeJournal()
    with pytest.raises(RuntimeError):
        await expire_pending_entry(
            plan_hash=PLAN_HASH,
            symbol=SYMBOL,
            adapter=adapter,  # type: ignore[arg-type]
            journal=journal,
            now_utc=NOW_UTC,
            trigger_reason="expiry_time",
        )
    assert journal.phases() == [(ENTRY_ID, "pre_cancel"), (ENTRY_ID, "cancel_failed")]
    assert json.loads(journal.events[-1].payload_json)["error_type"] == "RuntimeError"


async def test_cancel_untriggered_protectives_isolates_each_leg() -> None:
    """CR-10: one failing cancel must not leave the remaining legs live."""
    from src.execution.manager import cancel_untriggered_protectives

    adapter = ContractCancelAdapter(fail_ids=frozenset({SL_ID}))
    journal = FakeJournal()
    with pytest.raises(ExceptionGroup) as excinfo:
        await cancel_untriggered_protectives(
            plan_hash=PLAN_HASH,
            symbol=SYMBOL,
            adapter=adapter,  # type: ignore[arg-type]
            journal=journal,
            now_utc=NOW_UTC,
        )
    assert len(excinfo.value.exceptions) == 1
    assert [kw["client_algo_id"] for _, kw in adapter.calls] == [SL_ID, TP1_ID, TP2_ID]
    assert (SL_ID, "cancel_failed") in journal.phases()
    assert (TP1_ID, "post_cancel") in journal.phases()
    assert (TP2_ID, "post_cancel") in journal.phases()


async def test_emergency_close_blocks_first_and_runs_every_step_despite_failures() -> None:
    """CR-10: disable + SAFE_MODE happen BEFORE any cancel, and an entry
    cancel failure never aborts the protective cancels."""
    from src.execution.manager import emergency_manual_close

    order: list[str] = []
    adapter = ContractCancelAdapter(fail_ids=frozenset({ENTRY_ID}))
    journal = FakeJournal()
    enablement = RecordingEnablement(order)
    safe_mode = RecordingSafeMode(order)

    with pytest.raises(ExceptionGroup):
        await emergency_manual_close(
            plan_hash=PLAN_HASH,
            symbol=SYMBOL,
            adapter=adapter,  # type: ignore[arg-type]
            journal=journal,
            enablement=enablement,
            safe_mode_controller=safe_mode,
            operator_id="operator_alpha",
            now_utc=NOW_UTC,
        )

    assert order == ["disable", "safe_mode"]
    assert enablement.disabled is True
    assert safe_mode.reasons == ["MANUAL_CLOSE"]
    assert [method for method, _ in adapter.calls] == [
        "cancel_normal_order",
        "cancel_algo_order",
        "cancel_algo_order",
        "cancel_algo_order",
    ]


async def test_emergency_close_happy_path_raises_nothing() -> None:
    from src.execution.manager import emergency_manual_close

    order: list[str] = []
    adapter = ContractCancelAdapter()
    await emergency_manual_close(
        plan_hash=PLAN_HASH,
        symbol=SYMBOL,
        adapter=adapter,  # type: ignore[arg-type]
        journal=FakeJournal(),
        enablement=RecordingEnablement(order),
        safe_mode_controller=RecordingSafeMode(order),
        operator_id="operator_alpha",
        now_utc=NOW_UTC,
    )
    assert order == ["disable", "safe_mode"]
    assert len(adapter.calls) == 4


def test_real_adapter_exposes_every_cancel_method_the_protocol_declares() -> None:
    """CR-10: the Protocol's cancel surface exists on the real adapter
    with identical keyword names."""
    from src.execution.manager import ExecutionAdapter

    for name in ("cancel_normal_order", "cancel_algo_order"):
        proto = inspect.signature(getattr(ExecutionAdapter, name))
        real = inspect.signature(getattr(BinanceUsdmAdapter, name))
        assert list(proto.parameters) == list(real.parameters), name
