"""The coordinator's FLAT sweep keeps its audit rows in the spill while the journal is down (WR-A4).

`cancel_untriggered_protectives` takes a `spill` (D-16, F-702) but `ProtectionCoordinator._sweep`
did not pass the coordinator's own spill. With the journal down every leg then raised
`AuditRecordLost`, the sweep logged `PROTECTION_SWEEP_FAILED`, `sweep_done` was never set and each
following step cancelled and re-queried all three legs again until the journal returned. The legs
had been cancelled (the risk-reducing effect), but no record survived and the verdicts were never
seen.

Evidence label: executed tests with the Binance-semantics fake, a real `LocalSpill` in a temporary
directory and virtual time; no network.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from src.execution.protection import ProtectionState
from src.ops.spill import LocalSpill

from tests.support.protection_doubles import TEST_ONLY_PLAN_HASH, ProtectionRig, make_rig

D = Decimal


def _state(rig: ProtectionRig) -> ProtectionState:
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    return protection.state


async def _to_complete(rig: ProtectionRig) -> None:
    rig.coordinator.fill_sink(rig.stream_fill(D("0.010")))
    await rig.coordinator.step()
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.PROTECTED
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.COMPLETE


async def test_the_flat_sweep_spills_its_audit_rows_and_finishes_while_the_journal_is_down(
    tmp_path: Path,
) -> None:
    from src.execution.order_ids import derive_algo_client_id

    spill_dir = tmp_path / "spill"
    rig = await make_rig(spill=LocalSpill(spill_dir))
    await _to_complete(rig)
    rig.journal.fail = True  # the journal is down from here on
    rig.fake.trigger_stop(
        derive_algo_client_id(plan_hash=TEST_ONLY_PLAN_HASH, role="TAKE_PROFIT_2")
    )

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.FLAT
    # Every leg was cancelled once and its pre and post image reached the spill.
    assert len(rig.fake.calls_to("cancel_algo_order")) == 3
    spilled = sorted(p.name for p in spill_dir.glob("*.json"))
    assert len(spilled) == 6, spilled  # three legs x (pre_cancel, post_cancel)

    # The sweep is done: later steps do not cancel and query the legs again.
    await rig.coordinator.step()
    await rig.coordinator.step()
    assert len(rig.fake.calls_to("cancel_algo_order")) == 3
