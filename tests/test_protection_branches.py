"""The failure branches of the protection coordinator (plan 19-14; D-11, D-12, D-13, D034).

One deterministic offline race test per branch of 19-NOTES.md "Fill, stop and entry remainder",
run against the stateful Phase 19 fake exchange (constructed with
`enforce_flat_stop_rejection=True`), the real `MarketEmergencyCloser` over the same fake, scripted
completion gates and virtual time. Nothing sleeps and nothing touches a network. A green test
proves agreement with the fake's labelled rules, not with mainnet: the -2021 / -4509 answers are
Demo-observed only, the -2022 / -2024 answers of a reduce-only close are a TEST CONVENTION, and
no number here is a ratified limit (the deadlines are the TEST_ONLY values of
tests/support/execution_limits.py).

Open and NOT claimed safe here: Q4 / Phase 18 src/WR-12 (a 418/429 pause refuses the stop, the
cancel and the close), A3 (whether a closePosition stop is auto-cancelled when the position
closes), A2 (a GTD expiry reported as EXPIRED and terminal).
"""

from __future__ import annotations

import json
from decimal import Decimal

from src.domain.enums import ExecutionIntentStatus
from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import ProtectionState

from tests.support.protection_doubles import (
    TEST_ONLY_PLAN_HASH,
    ProtectionRig,
    make_rig,
)

D = Decimal


def _state(rig: ProtectionRig) -> ProtectionState:
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    return protection.state


def _transition_reasons(rig: ProtectionRig) -> list[tuple[str, str, str]]:
    """The journaled (from, to, reason) triples of the plan, in recording order."""
    out = []
    for event in rig.journal.calls:
        if event.event_type == "PROTECTION_TRANSITION":
            body = json.loads(event.payload_json)
            out.append((body["from"], body["to"], body["reason"]))
    return out


# --------------------------------------------------------------------------- #
# B5 (tracer): -2021 after a fill, end to end to CLOSE_REQUIRED, the close and FLAT.
# --------------------------------------------------------------------------- #


async def test_branch_b5_definitive_stop_rejection_after_a_fill_closes_and_ends_flat() -> None:
    rig = await make_rig(real_closer=True)
    rig.fake.reject_next_algo(-2021)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))

    await rig.coordinator.step()

    # The stop was rejected definitively: the intent is REJECTED and the plan must be closed.
    stop_row = rig.stop_row()
    assert stop_row is not None
    assert stop_row.intent_status is ExecutionIntentStatus.REJECTED
    assert _state(rig) is ProtectionState.CLOSE_REQUIRED
    assert rig.coordinator.blocks_new_entries() is True
    assert rig.safe_mode.entered_reasons == ["CLOSE_REQUIRED"]
    assert [(a.event, a.reason, a.plan_hash) for a in rig.alerts.alerts] == [
        ("CLOSE_REQUIRED", "B5_STOP_REJECTED", TEST_ONLY_PLAN_HASH)
    ]
    transitions = _transition_reasons(rig)
    assert transitions[-1] == ("UNPROTECTED", "CLOSE_REQUIRED", "B5_STOP_REJECTED")

    # The entry remainder cancel was issued and exactly one reduce-only MARKET close went out.
    assert len(rig.fake.calls_to("cancel_normal_order")) >= 1
    closes = rig.fake.calls_to("place_market_close")
    assert len(closes) == 1
    assert closes[0]["kwargs"]["quantity"] == D("0.004")
    assert closes[0]["kwargs"]["side"] == "SELL"
    assert closes[0]["kwargs"]["position_side"] == "BOTH"
    assert rig.fake.positions["BTCUSDT"] == D("0")

    # The stop is never resent, in this step or in any later one.
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.FLAT
    assert rig.coordinator.blocks_new_entries() is False
    await rig.coordinator.step()
    await rig.coordinator.step()
    assert len(rig.fake.calls_to("place_algo_protective")) == 1
    assert len(rig.fake.calls_to("place_market_close")) == 1

    # After FLAT the protective legs are swept once, by deterministic id (SL, TP1, TP2).
    swept = [c["kwargs"]["client_algo_id"] for c in rig.fake.calls_to("cancel_algo_order")]
    assert swept == [
        derive_algo_client_id(plan_hash=TEST_ONLY_PLAN_HASH, role=role)
        for role in ("STOP_LOSS", "TAKE_PROFIT_1", "TAKE_PROFIT_2")
    ]
    assert rig.safe_mode.entered_reasons == ["CLOSE_REQUIRED"]  # still only the one entry
    assert [t[:2] for t in _transition_reasons(rig)][-2:] == [
        ("UNPROTECTED", "CLOSE_REQUIRED"),
        ("CLOSE_REQUIRED", "FLAT"),
    ]
    assert len(rig.alerts.alerts) == 1


async def test_branch_b5_never_reads_exception_message_text() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src/execution/protection.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("error_message", ".message", "str(exc)", "str(answer)"):
        assert forbidden not in source, forbidden
