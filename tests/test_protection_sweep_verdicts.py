"""The coordinator sweep completes only for legs that are proven gone (Phase 20, plan 20-17).

Plan 20-11 made `cancel_untriggered_protectives` return a `{role: CancelVerdict}` map but left
`ProtectionCoordinator._sweep` ignoring it: the sweep was marked done whenever the call did not
raise, even when a leg verified UNKNOWN or STILL_OPEN (11-SUMMARY "Not done", 14-SUMMARY "For
dependents"). Now `sweep_done` becomes True only when every leg is in `PROVEN_GONE`
(CANCELED or GONE_NOT_CANCELED); anything else is journaled with the verdict names and the next
step sweeps again. The retry is idempotent (a cancel by deterministic id).

Evidence label: executed tests with the Binance-semantics fake and virtual time; no network.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import ProtectionState

from tests.support.protection_doubles import TEST_ONLY_PLAN_HASH, ProtectionRig, make_rig

D = Decimal
STOP_ID = derive_algo_client_id(plan_hash=TEST_ONLY_PLAN_HASH, role="STOP_LOSS")
TP1_ID = derive_algo_client_id(plan_hash=TEST_ONLY_PLAN_HASH, role="TAKE_PROFIT_1")
TP2_ID = derive_algo_client_id(plan_hash=TEST_ONLY_PLAN_HASH, role="TAKE_PROFIT_2")
UNVERIFIED = "PROTECTION_SWEEP_UNVERIFIED"


def _state(rig: ProtectionRig) -> ProtectionState:
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    return protection.state


def _stop_cancels(rig: ProtectionRig) -> int:
    return len(
        [
            c
            for c in rig.fake.calls_to("cancel_algo_order")
            if c["kwargs"]["client_algo_id"] == STOP_ID
        ]
    )


def _unverified_rows(rig: ProtectionRig) -> list[dict[str, Any]]:
    return [json.loads(e.payload_json) for e in rig.journal.calls if e.event_type == UNVERIFIED]


class _Behavior:
    """Switches of the wrapped fake: a stop cancel that does not take, an unreadable stop."""

    def __init__(self) -> None:
        self.sticky_stop = False
        self.unreadable_after_cancel = False
        self._cancelled_once = False


def _wrap(rig: ProtectionRig) -> _Behavior:
    behavior = _Behavior()
    fake = rig.fake
    cancel = fake.cancel_algo_order
    query = fake.query_algo_order_by_client

    async def cancel_wrapper(**kwargs: Any) -> Any:
        if kwargs["client_algo_id"] == STOP_ID:
            behavior._cancelled_once = True
            if behavior.sticky_stop:
                fake._bind_real("cancel_algo_order", kwargs)
                fake._record_call("cancel_algo_order", kwargs)
                return None
        return await cancel(**kwargs)

    async def query_wrapper(**kwargs: Any) -> Any:
        if (
            kwargs["client_algo_id"] == STOP_ID
            and behavior.unreadable_after_cancel
            and behavior._cancelled_once
        ):
            fake.fail_next("query_algo_order_by_client", RuntimeError("scripted read failure"))
        return await query(**kwargs)

    fake.cancel_algo_order = cancel_wrapper  # type: ignore[method-assign]
    fake.query_algo_order_by_client = query_wrapper  # type: ignore[method-assign]
    return behavior


async def _to_complete(rig: ProtectionRig) -> None:
    rig.coordinator.fill_sink(rig.stream_fill(D("0.010")))
    await rig.coordinator.step()
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.PROTECTED
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.COMPLETE


async def test_a_stop_that_is_still_open_after_the_cancel_keeps_the_sweep_open() -> None:
    rig = await make_rig()
    behavior = _wrap(rig)
    await _to_complete(rig)
    behavior.sticky_stop = True
    rig.fake.trigger_stop(TP2_ID)  # a closePosition TP consumes the position

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.FLAT
    assert _stop_cancels(rig) == 1
    rows = _unverified_rows(rig)
    assert len(rows) == 1
    assert rows[0]["legs"]["STOP_LOSS"] == "STILL_OPEN"
    assert STOP_ID in rig.fake.open_algos

    # The next step sweeps again (the sweep is not done) and, once the cancel takes, finishes.
    await rig.coordinator.step()
    assert _stop_cancels(rig) == 2
    assert len(_unverified_rows(rig)) == 2
    behavior.sticky_stop = False
    await rig.coordinator.step()
    assert _stop_cancels(rig) == 3
    assert STOP_ID not in rig.fake.open_algos
    assert len(_unverified_rows(rig)) == 2

    # Done now: a further step does not sweep again.
    await rig.coordinator.step()
    assert _stop_cancels(rig) == 3


async def test_a_leg_that_cannot_be_verified_keeps_the_sweep_open() -> None:
    rig = await make_rig()
    behavior = _wrap(rig)
    await _to_complete(rig)
    behavior.unreadable_after_cancel = True
    rig.fake.trigger_stop(TP2_ID)

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.FLAT
    rows = _unverified_rows(rig)
    assert len(rows) == 1
    assert rows[0]["legs"]["STOP_LOSS"] == "UNKNOWN"
    await rig.coordinator.step()
    assert _stop_cancels(rig) == 2, "an unverified leg is cancelled and looked at again"


async def test_every_leg_proven_gone_completes_the_sweep_at_once() -> None:
    rig = await make_rig()
    _wrap(rig)
    await _to_complete(rig)
    rig.fake.trigger_stop(STOP_ID)  # the stop consumed the position: FINISHED, GONE_NOT_CANCELED

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.FLAT
    assert _unverified_rows(rig) == []
    assert _stop_cancels(rig) == 1
    await rig.coordinator.step()
    assert _stop_cancels(rig) == 1, "a completed sweep is not repeated"
    assert rig.fake.open_algos == {}


async def test_the_unverified_row_names_verdicts_and_roles_only() -> None:
    rig = await make_rig()
    behavior = _wrap(rig)
    await _to_complete(rig)
    behavior.sticky_stop = True
    rig.fake.trigger_stop(TP2_ID)

    await rig.coordinator.step()

    row = _unverified_rows(rig)[0]
    assert set(row["legs"]) == {"STOP_LOSS", "TAKE_PROFIT_1", "TAKE_PROFIT_2"}
    assert all(isinstance(v, str) for v in row["legs"].values())
    assert "trade_plan_id" in row and "symbol" in row
