"""The protection transition guard (plan 20-02; T-A, D-29, D077).

``ProtectionCoordinator._transition`` consults the PROTECTION table of
``src/domain/transitions.py`` (built from the ``ProtectionState`` docstring) and never assigns a
state the table does not allow. Every test runs offline against the stateful Phase 19 fake
exchange, the real ``MarketEmergencyCloser`` where a close is needed, and virtual time.

Evidence label: executed unit tests with fakes. Nothing here is a Binance Demo observation (no
[DEMO] claim), and general stale-event detection is NOT claimed: Phase 20 has no exchange
event-time column, so the guard detects only what ordering and deduplication evidence it has
(D-29, the rest is deferred to Phase 24).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from src.domain.transitions import LEGAL_TRANSITIONS, TransitionKind, is_legal
from src.execution.protection import ProtectionState

from tests.support.protection_doubles import TEST_ONLY_PLAN_HASH, ProtectionRig, make_rig

D = Decimal

EVENT_TRANSITION = "PROTECTION_TRANSITION"
EVENT_REJECTED = "PROTECTION_TRANSITION_REJECTED"
SAFE_MODE_INVALID = "PROTECTION_STATE_INVALID"


def _tracked(rig: ProtectionRig) -> Any:
    return rig.coordinator._tracked[TEST_ONLY_PLAN_HASH]  # noqa: SLF001 - the guard under test


def _rows(rig: ProtectionRig, event_type: str) -> list[dict[str, Any]]:
    return [json.loads(e.payload_json) for e in rig.journal.calls if e.event_type == event_type]


# --------------------------------------------------------------------------- #
# Tracer: the table and the guard, end to end through the real coordinator.
# --------------------------------------------------------------------------- #


def test_the_protection_table_keys_are_exactly_the_protection_state_names() -> None:
    from src.domain.transitions import PROTECTION_INITIAL_STATE

    assert set(LEGAL_TRANSITIONS[TransitionKind.PROTECTION]) == {s.value for s in ProtectionState}
    assert PROTECTION_INITIAL_STATE == ProtectionState.AWAITING_FILL.value


def test_the_table_allows_close_required_only_to_close_failed_or_flat() -> None:
    assert is_legal(TransitionKind.PROTECTION, "CLOSE_REQUIRED", "PROTECTED") is False
    assert is_legal(TransitionKind.PROTECTION, "CLOSE_REQUIRED", "CLOSE_FAILED") is True
    assert LEGAL_TRANSITIONS[TransitionKind.PROTECTION]["CLOSE_REQUIRED"] == {
        "CLOSE_FAILED",
        "FLAT",
    }


async def test_close_required_never_downgrades_to_protected() -> None:
    rig = await make_rig(real_closer=True)
    rig.fake.reject_next_algo(-2021)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()  # B5: the stop is rejected definitively, CLOSE_REQUIRED
    tracked = _tracked(rig)
    assert tracked.state is ProtectionState.CLOSE_REQUIRED
    seq_before = tracked.seq
    reason_before = tracked.last_reason
    transitions_before = len(_rows(rig, EVENT_TRANSITION))
    assert _rows(rig, EVENT_REJECTED) == []

    accepted = rig.coordinator._transition(  # noqa: SLF001 - the guard under test
        tracked, ProtectionState.PROTECTED, "LATE_STOP_CONFIRMED", rig.clock.now()
    )

    assert accepted is False
    assert tracked.state is ProtectionState.CLOSE_REQUIRED
    assert tracked.seq == seq_before
    assert tracked.last_reason == reason_before
    assert len(_rows(rig, EVENT_TRANSITION)) == transitions_before
    rejected = _rows(rig, EVENT_REJECTED)
    assert len(rejected) == 1
    assert rejected[0]["from"] == "CLOSE_REQUIRED"
    assert rejected[0]["to"] == "PROTECTED"
    assert rejected[0]["seq"] == seq_before
    assert rejected[0]["reason"] == "LATE_STOP_CONFIRMED"
    assert rig.safe_mode.entered_reasons == ["CLOSE_REQUIRED", SAFE_MODE_INVALID]
    assert rig.coordinator.blocks_new_entries() is True
