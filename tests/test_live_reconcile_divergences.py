"""G2-019 through the composed reconcile loop (plan 24-34, D-35).

Phase 20 built both surfaces: a client id that appears twice in the exchange truth is the
`DUPLICATE_EXCHANGE_ID` divergence, and an orphan-protective cancel the sweeper did not make is a
`SWEEP_SKIPPED` journal row (IN-14, D-03). This module closes the item by proving that each one
reaches its row, and for the divergence SAFE_MODE and the alert, through the objects that
`src.live.reconcile.build_reconcile` composes (the real loop, sweeper, SAFE_MODE controller and
alert sink; only the edges are fakes).

Evidence label: executed tests with the Binance-semantics fake and the reconcile doubles; no
network. A gate refusal is the real `RateLimitPauseActive` type; its value is a TEST_ONLY number.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from src.adapters.binance_ratelimit_gate import RateLimitPauseActive
from src.domain.enums import OrderRole
from src.live.alerts import drain_once
from src.live.reconcile import reconcile_tick_once
from src.reconcile.loop import TICK_COMPARED
from src.reconcile.sweeper import EVENT_SWEEP_SKIPPED

from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.live_rig import forbid_real_sleep
from tests.support.reconcile_doubles import FakeIntentStore, make_intent_record, make_open_order
from tests.test_live_reconcile_wiring import (
    ENTRY_ID,
    H1,
    NOW,
    SL_ID,
    SYMBOL,
    FilterAdapter,
    StepProtection,
    compose,
    place_orphan_leg,
)

D = Decimal


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


async def test_a_duplicate_exchange_client_id_is_journaled_enters_safe_mode_and_alerts() -> None:
    # The exchange truth shows the one system entry id twice (it should be unique).
    adapter = FilterAdapter(
        normal_orders=[make_open_order(ENTRY_ID, SYMBOL), make_open_order(ENTRY_ID, SYMBOL)]
    )
    parts = compose(
        adapter=adapter,
        coordinator=StepProtection(),
        intent_store=FakeIntentStore([make_intent_record(H1, OrderRole.ENTRY.value)]),
    )

    report = await reconcile_tick_once(parts.bundle, NOW)

    assert report.outcome == TICK_COMPARED
    assert report.agreement is False
    duplicates = [d for d in report.divergences if d.kind == "DUPLICATE_EXCHANGE_ID"]
    assert len(duplicates) == 1
    assert duplicates[0].client_order_id == ENTRY_ID
    # The journal row of the tick names the divergence by kind (counts), and SAFE_MODE is on.
    ticks = [e for e in parts.journal.events if e.entity_type == "ReconcileLoop"]
    assert any(
        json.loads(e.payload_json).get("counts", {}).get("DUPLICATE_EXCHANGE_ID") == 1
        for e in ticks
    )
    assert parts.safe_mode.in_safe_mode is True
    assert "DUPLICATE_EXCHANGE_ID" in report.safe_mode_reasons
    # The alert reached the sink and, drained, the bot; nothing was cancelled or placed.
    queued = {(a.event, a.reason) for a in parts.alerts.queue}
    assert ("DIVERGENCE", "DUPLICATE_EXCHANGE_ID") in queued
    delivered = await drain_once(parts.alerts)
    assert (delivered.delivered, delivered.failed) == (len(queued), 0)
    assert len(parts.bot.sent) == len(queued)
    assert adapter.cancelled_algo == [] and adapter.cancelled_normal == []
    assert adapter.forbidden_calls == []


async def test_a_sweeper_cancel_refused_by_the_gate_leaves_one_sweep_skipped_row() -> None:
    fake = BinanceSemanticsFakeAdapter(now_utc=NOW)
    await place_orphan_leg(fake)

    async def refused(*, symbol: str, client_algo_id: str) -> Any:
        fake._record_call("cancel_algo_order", {"client_algo_id": client_algo_id})
        raise RateLimitPauseActive(30)

    fake.cancel_algo_order = refused  # type: ignore[method-assign]
    parts = compose(
        adapter=fake,
        coordinator=StepProtection(),
        intent_store=FakeIntentStore([make_intent_record(H1, OrderRole.STOP_LOSS.value)]),
    )

    report = await reconcile_tick_once(parts.bundle, NOW)

    assert [d.kind for d in report.divergences] == ["ORPHAN_PROTECTIVE"]
    assert report.swept == ()
    assert report.sweep_skipped == ((SYMBOL, SL_ID),)
    assert SL_ID in fake.open_algos, "the refused cancel left the leg resting"
    rows = [e for e in parts.journal.events if e.event_type == EVENT_SWEEP_SKIPPED]
    assert len(rows) == 1
    payload = json.loads(rows[0].payload_json)
    assert payload == {
        "client_algo_id": SL_ID,
        "reason": "cancel_failed: RateLimitPauseActive",
        "symbol": SYMBOL,
    }
    # A reason code only: neither the refusal text nor its retry hint reached the journal.
    assert "retry_after" not in rows[0].payload_json
    assert "REST call refused" not in rows[0].payload_json
    assert rows[0].occurred_at_utc == NOW
    assert len(fake.calls_to("cancel_algo_order")) == 1, "no retry inside the tick"
