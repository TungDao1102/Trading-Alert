"""SHADOW exposure reservation lifecycle (Phase 16, plan 16-23, Task 3, D-17, G4-010).

The user's Q-C decision is `reserve-at-confirm` (`decisions/16-DEC-Q-C.md`): exposure is reserved
only when a valid CONFIRM is accepted AND its SHADOW_CONFIRMED journal write succeeded, lasts until
the plan's own expiry, and is rebuilt from the existing journal alone after a restart (Q-J). These
tests prove, one transition at a time:

- the reserve and release points (APPROVE, CONFIRM, SKIP, CANCEL, APPROVAL_EXPIRED, confirm TTL);
- the capacity gates of `check_portfolio` on the CURRENT ledger, including a reservation that is
  still waiting for its fill, for two sequential CONFIRMs and for a concurrent race;
- journal failure paths (not appended, appended with an unknown outcome, unreadable journal);
- recovery at every crash boundary, expiry while offline, replay without duplicates, and the
  deterministic journal ids and payloads PostgreSQL's `JournalConflict` rule requires;
- the fill (the reservation becomes the position, never counted twice) and the rebuild by replaying
  `advance` over recorded minutes, equal to an uninterrupted run, with holes reported not filled;
- compatibility of the new events with every fixed-list consumer.

Every equity and risk number is a TEST value chosen for hand arithmetic (REV-07).
No network, no wall clock: every instant is an explicit argument.
"""

from __future__ import annotations

import ast
import json
import threading
from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.backtest.constraints import select_constraints  # noqa: F401 - parity with fill tests
from src.backtest.lifecycle import EVENT_FILL
from src.backtest.series import ListMinuteSource, parse_minute_row
from src.domain.approval import Approval
from src.domain.enums import (
    ApprovalAction,
    ApprovalResult,
    RejectionReason,
)
from src.domain.journal import JournalEvent
from src.domain.registry import load_parameter_set
from src.paper import attribution, shadow_confirm, shadow_ledger
from src.paper.attribution import ShadowOutcome, attribute_shadow_outcome
from src.paper.shadow import ConfirmOutcome
from src.paper.shadow_confirm import (
    EVENT_SHADOW_CONFIRM_EXPIRED,
    EVENT_SHADOW_CONFIRMED,
    TERMINAL_CONFIRM_EVENTS,
    assert_no_stranded_approvals,
)
from src.paper.shadow_fill import FundingHistory, eligibility_start_for
from src.paper.shadow_ledger import (
    CORRELATION_PREFIX,
    EVENT_SHADOW_PLAN_EXPIRED_UNFILLED,
    EVENT_SHADOW_POSITION_OPENED,
    EVENT_SHADOW_RESERVATION_REFUSED,
    RESERVATION_EVENTS,
    PositionRecord,
    Reservation,
    ReservationBasis,
    ShadowLedger,
    ShadowReservations,
)
from src.persistence.errors import JournalConflict, ParentRowMissing

from tests.backtest_case_helpers import DATA_END, SIGNAL_CLOSE, at
from tests.shadow_fakes import (
    CHAT_ID,
    T0,
    USER_ID,
    InMemoryShadowStores,
    make_shadow_plan,
    make_shadow_signal,
)
from tests.test_paper_shadow_confirm import T_PRESS, Harness
from tests.test_paper_shadow_fill import (
    QUANTITY,
    REALIZED_RISK,
    _driver,
    _funding,
    _outcome,
    _source,
    _tracer,
)

PARAMS = load_parameter_set("trend-pullback", "baseline-v5").params
# Test equity: with baseline-v5 rates the caps are cluster 50, aggregate 100, max 2 positions.
EQUITY = Decimal("10000")
START = T0 - timedelta(hours=1)
PLAN_EXPIRY = T0 + timedelta(hours=4)
QTY = Decimal("0.08")
SHADOW_LEDGER_PATH = Path(__file__).resolve().parent.parent / "src" / "paper" / "shadow_ledger.py"


# --------------------------------------------------------------------------- #
# Fakes: PostgreSQL-like strict journal with fault injection.
# --------------------------------------------------------------------------- #


class FaultyStores(InMemoryShadowStores):
    """In-memory stores with the journal rules of `PgJournalStore` and injectable faults.

    A repeated id with the same identity and payload is a no-op, with a different payload it
    raises `JournalConflict` (`occurred_at_utc` is not compared); a missing parent raises
    `ParentRowMissing` (inherited). `fail_types` makes `record_journal` raise for those event
    types: `commit_then_raise` stores the event first (an unknown outcome), otherwise nothing is
    stored. `unreadable` makes the journal reader raise.
    """

    def __init__(self, trace: list[str] | None = None) -> None:
        super().__init__(trace)
        self.fail_types: set[str] = set()
        self.commit_then_raise = False
        self.unreadable = False

    def record_journal(self, event: JournalEvent) -> None:
        if event.event_type in self.fail_types:
            if self.commit_then_raise:
                self._strict_record(event)
            raise ConnectionError("journal connection lost")
        self._strict_record(event)

    def _strict_record(self, event: JournalEvent) -> None:
        for stored in self.journal:
            if stored.journal_event_id == event.journal_event_id:
                same = (
                    stored.event_type == event.event_type
                    and stored.entity_type == event.entity_type
                    and stored.entity_id == event.entity_id
                    and stored.correlation_id == event.correlation_id
                    and stored.signal_id == event.signal_id
                    and stored.trade_plan_id == event.trade_plan_id
                    and stored.approval_id == event.approval_id
                    and stored.payload_json == event.payload_json
                )
                if not same:
                    raise JournalConflict(f"journal id {event.journal_event_id} differs")
                return
        super().record_journal(event)

    def journal_for_correlation(self, correlation_id: str) -> list[JournalEvent]:
        if self.unreadable:
            raise ConnectionError("journal unreadable")
        return super().journal_for_correlation(correlation_id)


class RecordingStores:
    """A parent-free journal for the tests that build their own records."""

    def __init__(self) -> None:
        self.journal: list[JournalEvent] = []

    def record_journal(self, event: JournalEvent) -> None:
        if all(e.journal_event_id != event.journal_event_id for e in self.journal):
            self.journal.append(event)

    def list_approved_approvals(self) -> list[Approval]:
        return []

    def journal_for_correlation(self, correlation_id: str) -> list[JournalEvent]:
        return [e for e in self.journal if e.correlation_id == correlation_id]


class Rig:
    """One paper epoch: stores, ledger and reservations; `restart()` builds a fresh process."""

    def __init__(self, stores: FaultyStores | None = None) -> None:
        self.stores = stores if stores is not None else FaultyStores()
        self.bases: dict[str, ReservationBasis] = {}
        self.ledger, self.reservations = self._build()

    def _build(self) -> tuple[ShadowLedger, ShadowReservations]:
        ledger = ShadowLedger(
            initial_equity=EQUITY, parameter_set_params=PARAMS, started_at_utc=START
        )
        return ledger, ShadowReservations(ledger, self.stores, basis_for=self._basis)

    def _basis(self, signal: Any, plan: Any) -> ReservationBasis | None:
        return self.bases.get(plan.plan_hash)

    def restart(self) -> Rig:
        """A new process on the same journal and the same basis source (nothing else survives)."""
        other = Rig.__new__(Rig)
        other.stores = self.stores
        other.bases = self.bases
        other.ledger, other.reservations = other._build()
        return other

    def positions(self, now: Any = T_PRESS) -> list[tuple[str, str, Decimal]]:
        found, _loss = self.ledger.risk_inputs(now)
        return [(p.symbol, p.position_side, p.open_risk) for p in found]

    def rebuild(self, now: Any, **kwargs: Any) -> shadow_ledger.RebuildReport:
        return self.reservations.rebuild_from_records(
            self.reservations.load_records(), None, now_utc=now, **kwargs
        )


async def approved(
    rig: Rig,
    n: int,
    *,
    symbol: str = "BTCUSDT",
    direction: str = "LONG",
    risk: str = "10",
    expiry: Any = None,
    reservations: Any = None,
    recheck: Any = None,
) -> tuple[Harness, str]:
    """Alert, then APPROVE, of plan `n`: returns its harness and the confirm short id."""
    harness = Harness(
        stores=rig.stores,
        reservations=rig.reservations if reservations is None else reservations,
        recheck=recheck,
    )
    harness.signal = make_shadow_signal(n, symbol=symbol, direction=direction)
    overrides: dict[str, Any] = {"plan_hash": str(n) * 64}
    if expiry is not None:
        overrides["expiry_utc"] = expiry
    harness.plan = make_shadow_plan(harness.signal, **overrides)
    rig.bases[harness.plan.plan_hash] = ReservationBasis(Decimal(risk), QTY)
    short_id = await harness.approve(query=f"q-apr-{n}")
    return harness, short_id


def press_confirm(h: Harness, short_id: str, now: Any = T_PRESS) -> Any:
    return h.confirm.handle_confirm(
        short_id=short_id,
        chat_id=CHAT_ID,
        authorized_chat_id=CHAT_ID,
        from_user_id=USER_ID,
        now_utc=now,
        correlation_id=f"cb-{short_id}-{now.isoformat()}",
    )


def types(stores: InMemoryShadowStores, event_type: str) -> list[JournalEvent]:
    return stores.journal_of_type(event_type)


# --------------------------------------------------------------------------- #
# Reserve and release points per transition (Q-C reserve-at-confirm).
# --------------------------------------------------------------------------- #


async def test_approve_reserves_nothing() -> None:
    rig = Rig()
    await approved(rig, 1)
    assert rig.reservations.pending_reservations() == ()
    assert rig.positions() == []


async def test_confirm_reserves_exposure_and_journals_the_reservation_facts() -> None:
    rig = Rig()
    h, short_id = await approved(rig, 1, risk="10")
    result = press_confirm(h, short_id)
    assert result.outcome is ConfirmOutcome.CONFIRMED
    assert rig.positions() == [("BTCUSDT", "LONG", Decimal("10"))]
    (confirmed,) = types(rig.stores, EVENT_SHADOW_CONFIRMED)
    body = json.loads(confirmed.payload_json)["reservation"]
    assert body["plan_hash"] == "1" * 64
    assert body["sized_realized_risk"] == "10"
    assert body["plan_expiry_utc"] == PLAN_EXPIRY.isoformat()
    # Q-B confirm-plus-one: the minute after the CONFIRM minute (T_PRESS is on a minute boundary).
    assert body["eligibility_start_utc"] == (T_PRESS + timedelta(minutes=1)).isoformat()
    assert len(h.confirmed) == 1


async def test_skip_reserves_nothing() -> None:
    rig = Rig()
    h = Harness(stores=rig.stores, reservations=rig.reservations)
    await h.alert()
    _apr, skp = h.alert_buttons()
    await h.tap(skp, "q-skp")
    assert rig.reservations.pending_reservations() == ()
    assert rig.positions() == []


async def test_cancel_after_approve_reserves_nothing() -> None:
    rig = Rig()
    h, short_id = await approved(rig, 1)
    h.confirm.handle_cancel(
        short_id=short_id,
        chat_id=CHAT_ID,
        authorized_chat_id=CHAT_ID,
        from_user_id=USER_ID,
        now_utc=T_PRESS,
        correlation_id="cb-cancel",
    )
    assert rig.reservations.pending_reservations() == ()
    assert rig.positions() == []


async def test_an_approve_after_the_plan_expiry_reserves_nothing() -> None:
    rig = Rig()
    h = Harness(stores=rig.stores, reservations=rig.reservations)
    await h.alert()
    apr, _skp = h.alert_buttons()
    h.now = PLAN_EXPIRY + timedelta(seconds=1)
    await h.tap(apr, "q-late")
    assert rig.reservations.pending_reservations() == ()
    assert rig.positions(h.now) == []


async def test_the_confirm_ttl_expiring_reserves_nothing_and_is_not_a_reservation_expiry() -> None:
    rig = Rig()
    h, short_id = await approved(rig, 1)
    late = T_PRESS + timedelta(seconds=61)
    assert h.confirm.expire_due(late)
    result = press_confirm(h, short_id, late)
    assert result.outcome is not ConfirmOutcome.CONFIRMED
    assert rig.positions(late) == []
    assert len(types(rig.stores, EVENT_SHADOW_CONFIRM_EXPIRED)) >= 1
    assert rig.reservations.release_expired(late) == []
    assert types(rig.stores, EVENT_SHADOW_PLAN_EXPIRED_UNFILLED) == []


async def test_a_confirmed_unfilled_plan_keeps_its_reservation_until_the_plan_expires() -> None:
    rig = Rig()
    h, short_id = await approved(rig, 1)
    press_confirm(h, short_id)
    later = T_PRESS + timedelta(minutes=30)  # far past the 60 s confirm TTL
    h.confirm.expire_due(later)
    assert rig.reservations.release_expired(later) == []
    assert len(rig.reservations.pending_reservations()) == 1
    assert rig.positions(later) == [("BTCUSDT", "LONG", Decimal("10"))]
    assert types(rig.stores, EVENT_SHADOW_CONFIRM_EXPIRED) == []
    assert types(rig.stores, EVENT_SHADOW_PLAN_EXPIRED_UNFILLED) == []
    # One tick before the plan expiry it is still held (inclusive boundary at the expiry).
    assert rig.reservations.release_expired(PLAN_EXPIRY - timedelta(milliseconds=1)) == []


async def test_expiry_without_a_fill_releases_exactly_once() -> None:
    rig = Rig()
    h, short_id = await approved(rig, 1)
    press_confirm(h, short_id)
    approval_id = h.confirm.get(short_id).approval.approval_id  # type: ignore[union-attr]
    assert rig.reservations.release_expired(PLAN_EXPIRY) == [approval_id]
    assert rig.reservations.release_expired(PLAN_EXPIRY + timedelta(hours=1)) == []
    assert rig.reservations.pending_reservations() == ()
    assert rig.positions(PLAN_EXPIRY) == []
    (event,) = types(rig.stores, EVENT_SHADOW_PLAN_EXPIRED_UNFILLED)
    body = json.loads(event.payload_json)
    assert body["reason"] == "PLAN_EXPIRED_UNFILLED"
    assert body["plan_hash"] == "1" * 64
    assert event.occurred_at_utc == PLAN_EXPIRY  # stable data, not the sweep clock
    # The CONFIRM history stays for audit and the plan cannot reserve again.
    assert len(types(rig.stores, EVENT_SHADOW_CONFIRMED)) == 1
    again = rig.reservations.reserve(
        approval=h.confirm.get(short_id).approval,  # type: ignore[union-attr]
        signal=h.signal,
        plan=h.plan,
        short_id=short_id,
        confirmed_at_utc=T_PRESS,
    )
    assert not again.reserved


async def test_a_confirm_with_no_valid_fill_window_creates_no_reservation() -> None:
    rig = Rig()
    expiry = T_PRESS + timedelta(seconds=30)
    h, short_id = await approved(rig, 1, expiry=expiry)
    # 10 s after the card: the plan is still valid but no whole minute opens before its expiry.
    result = press_confirm(h, short_id, T_PRESS + timedelta(seconds=10))
    assert result.outcome is ConfirmOutcome.REJECTED_OTHER
    assert result.reason == RejectionReason.APPROVAL_EXPIRED.value
    assert rig.reservations.pending_reservations() == ()
    assert types(rig.stores, EVENT_SHADOW_CONFIRMED) == []
    assert h.confirmed == []
    status = eligibility_start_for(
        signal_close_utc=h.signal.source_candle_close_utc,
        plan_expiry_utc=expiry,
        confirm_outcome="CONFIRMED",
        confirmed_at_utc=T_PRESS + timedelta(seconds=10),
    ).status
    assert status == "NO_MINUTE_BEFORE_EXPIRY"


# --------------------------------------------------------------------------- #
# Capacity on the current ledger (cluster, aggregate, position count, symbol).
# --------------------------------------------------------------------------- #


async def test_a_waiting_reservation_counts_in_the_next_confirms_risk_inputs() -> None:
    rig = Rig()
    first, s1 = await approved(rig, 1, symbol="DOGEUSDT", risk="30")
    second, s2 = await approved(rig, 2, symbol="ADAUSDT", risk="20")
    press_confirm(first, s1)
    positions, _loss = rig.ledger.risk_inputs(T_PRESS)
    assert [(p.symbol, p.open_risk) for p in positions] == [("DOGEUSDT", Decimal("30"))]
    assert press_confirm(second, s2).outcome is ConfirmOutcome.CONFIRMED
    assert rig.positions() == [
        ("ADAUSDT", "LONG", Decimal("20")),
        ("DOGEUSDT", "LONG", Decimal("30")),
    ]


@pytest.mark.parametrize(
    ("first", "second", "reason"),
    [
        # Cluster cap 50: BTC and ETH LONG count as one cluster (30 + 30).
        (("BTCUSDT", "30"), ("ETHUSDT", "30"), "CLUSTER_CAP_REJECT"),
        # Aggregate cap 100 outside the cluster (60 + 60).
        (("DOGEUSDT", "60"), ("ADAUSDT", "60"), "AGGREGATE_CAP_REJECT"),
        # Same symbol twice: the engine's own conflict label.
        (("BTCUSDT", "10"), ("BTCUSDT", "10"), "CONFLICT_WITH_OPEN_POSITION"),
    ],
)
async def test_two_sequential_confirms_cannot_exceed_the_remaining_capacity(
    first: tuple[str, str], second: tuple[str, str], reason: str
) -> None:
    rig = Rig()
    h1, s1 = await approved(rig, 1, symbol=first[0], risk=first[1])
    h2, s2 = await approved(rig, 2, symbol=second[0], risk=second[1])
    assert press_confirm(h1, s1).outcome is ConfirmOutcome.CONFIRMED
    refused = press_confirm(h2, s2)
    assert refused.outcome is ConfirmOutcome.REJECTED_OTHER
    assert refused.reason == reason
    assert rig.positions() == [(first[0], "LONG", Decimal(first[1]))]
    assert len(rig.reservations.pending_reservations()) == 1
    assert h2.confirmed == []
    (expired,) = types(rig.stores, EVENT_SHADOW_CONFIRM_EXPIRED)
    assert json.loads(expired.payload_json)["reason"] == reason
    assert len(types(rig.stores, EVENT_SHADOW_CONFIRMED)) == 1


async def test_the_position_count_gate_applies_to_reservations() -> None:
    rig = Rig()
    rigs = []
    for n, symbol in enumerate(("DOGEUSDT", "ADAUSDT", "LINKUSDT"), start=1):
        rigs.append(await approved(rig, n, symbol=symbol, risk="10"))
    assert press_confirm(*rigs[0]).outcome is ConfirmOutcome.CONFIRMED
    assert press_confirm(*rigs[1]).outcome is ConfirmOutcome.CONFIRMED
    third = press_confirm(*rigs[2])
    assert third.reason == "MAX_POSITIONS_REJECT"
    assert len(rig.positions()) == 2


async def test_two_concurrent_reserves_cannot_exceed_the_remaining_capacity() -> None:
    rig = Rig()
    h1, s1 = await approved(rig, 1, symbol="DOGEUSDT", risk="60")
    h2, s2 = await approved(rig, 2, symbol="ADAUSDT", risk="60")
    barrier = threading.Barrier(2)
    results: list[Any] = []

    def attempt(h: Harness, short_id: str) -> None:
        entry = h.confirm.get(short_id)
        assert entry is not None
        barrier.wait()
        results.append(
            rig.reservations.reserve(
                approval=entry.approval,
                signal=entry.signal,
                plan=entry.plan,
                short_id=short_id,
                confirmed_at_utc=T_PRESS,
            )
        )

    threads = [
        threading.Thread(target=attempt, args=(h1, s1)),
        threading.Thread(target=attempt, args=(h2, s2)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(r.reserved for r in results) == [False, True]
    assert [r.reason_code for r in results if not r.reserved] == ["AGGREGATE_CAP_REJECT"]
    assert len(rig.positions()) == 1
    assert len(types(rig.stores, EVENT_SHADOW_RESERVATION_REFUSED)) == 1


# --------------------------------------------------------------------------- #
# Recheck and journal failure paths: no reservation, no false successful CONFIRM.
# --------------------------------------------------------------------------- #


async def test_a_failed_recheck_leaves_no_reservation_and_no_confirmed_event() -> None:
    rig = Rig()
    h, short_id = await approved(
        rig, 1, recheck=lambda signal, plan, now: RejectionReason.STALE_SETUP
    )
    result = press_confirm(h, short_id)
    assert result.outcome is ConfirmOutcome.REJECTED_OTHER
    assert rig.reservations.pending_reservations() == ()
    assert types(rig.stores, EVENT_SHADOW_CONFIRMED) == []
    assert h.confirmed == []


async def test_a_recheck_that_raises_fails_closed() -> None:
    def broken(signal: Any, plan: Any, now: Any) -> Any:
        raise RuntimeError("boom")

    rig = Rig()
    h, short_id = await approved(rig, 1, recheck=broken)
    result = press_confirm(h, short_id)
    assert result.reason == shadow_confirm.REASON_RECHECK_ERROR
    assert rig.positions() == []


async def test_a_missing_sizing_basis_fails_closed() -> None:
    rig = Rig()
    h, short_id = await approved(rig, 1)
    rig.bases.clear()
    result = press_confirm(h, short_id)
    assert result.outcome is ConfirmOutcome.REJECTED_OTHER
    assert result.reason == RejectionReason.UNCERTAIN_ACCOUNT_STATE.value
    assert rig.positions() == []


async def test_a_journal_write_that_fails_reserves_nothing_and_confirms_nothing() -> None:
    rig = Rig()
    h, short_id = await approved(rig, 1)
    rig.stores.fail_types = {EVENT_SHADOW_CONFIRMED}
    with pytest.raises(ConnectionError):
        press_confirm(h, short_id)
    assert rig.positions() == []
    assert rig.reservations.pending_reservations() == ()
    assert h.confirmed == []
    entry = h.confirm.get(short_id)
    assert entry is not None and entry.state is shadow_confirm.ConfirmState.PENDING
    # The journal recovers: the same CONFIRM press now succeeds once.
    rig.stores.fail_types = set()
    assert press_confirm(h, short_id, T_PRESS + timedelta(seconds=5)).outcome is (
        ConfirmOutcome.CONFIRMED
    )
    assert len(rig.positions()) == 1
    assert len(types(rig.stores, EVENT_SHADOW_CONFIRMED)) == 1


async def test_an_append_with_an_unknown_outcome_is_reconciled_against_the_journal() -> None:
    rig = Rig()
    h, short_id = await approved(rig, 1)
    rig.stores.fail_types = {EVENT_SHADOW_CONFIRMED}
    rig.stores.commit_then_raise = True
    result = press_confirm(h, short_id)  # the append committed but the caller saw an error
    assert result.outcome is ConfirmOutcome.CONFIRMED
    assert len(types(rig.stores, EVENT_SHADOW_CONFIRMED)) == 1  # not appended a second time
    assert len(rig.positions()) == 1
    assert len(h.confirmed) == 1


async def test_an_unreadable_journal_after_an_unknown_append_fails_closed_then_adopts() -> None:
    rig = Rig()
    h, short_id = await approved(rig, 1)
    rig.stores.fail_types = {EVENT_SHADOW_CONFIRMED}
    rig.stores.commit_then_raise = True
    rig.stores.unreadable = True
    with pytest.raises(ConnectionError):
        press_confirm(h, short_id)
    assert rig.positions() == []  # nothing reserved while the outcome is unknown
    assert h.confirmed == []
    # The journal is back; a retry at a LATER instant adopts the stored CONFIRM and its stored
    # confirm instant instead of appending a different payload under the same id.
    rig.stores.unreadable = False
    rig.stores.fail_types = set()
    retry = T_PRESS + timedelta(seconds=20)
    result = press_confirm(h, short_id, retry)
    assert result.outcome is ConfirmOutcome.CONFIRMED
    (reservation,) = rig.reservations.pending_reservations()
    assert reservation.confirmed_at_utc == T_PRESS
    assert reservation.eligibility_start_utc == T_PRESS + timedelta(minutes=1)
    assert len(types(rig.stores, EVENT_SHADOW_CONFIRMED)) == 1


async def test_a_later_retry_with_a_different_payload_would_conflict_without_the_reconcile() -> (
    None
):
    """The trap itself: the same id with a different confirm instant is a JournalConflict."""
    rig = Rig()
    h, short_id = await approved(rig, 1)
    press_confirm(h, short_id)
    (stored,) = types(rig.stores, EVENT_SHADOW_CONFIRMED)
    payload = json.loads(stored.payload_json)
    payload["confirmed_at_utc"] = (T_PRESS + timedelta(seconds=20)).isoformat()
    other = JournalEvent(
        journal_event_id=stored.journal_event_id,
        occurred_at_utc=stored.occurred_at_utc,
        event_type=stored.event_type,
        entity_type=stored.entity_type,
        entity_id=stored.entity_id,
        correlation_id=stored.correlation_id,
        signal_id=stored.signal_id,
        trade_plan_id=stored.trade_plan_id,
        approval_id=stored.approval_id,
        payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
    )
    with pytest.raises(JournalConflict):
        rig.stores.record_journal(other)


# --------------------------------------------------------------------------- #
# Crash boundaries and recovery from the journal (Q-J).
# --------------------------------------------------------------------------- #


class CrashingReserve:
    """The reservation port whose `reserve` dies: a crash between the journal and the ledger."""

    def __init__(self, inner: ShadowReservations) -> None:
        self._inner = inner
        self.crash = True

    def section(self) -> Any:
        return self._inner.section()

    def check(self, *args: Any, **kwargs: Any) -> Any:
        return self._inner.check(*args, **kwargs)

    def confirm_payload(self, **kwargs: Any) -> Any:
        return self._inner.confirm_payload(**kwargs)

    def reserve(self, **kwargs: Any) -> Any:
        if self.crash:
            raise RuntimeError("process died before the reservation")
        return self._inner.reserve(**kwargs)


async def test_crash_before_the_journal_append_loses_nothing_and_invents_nothing() -> None:
    rig = Rig()
    h, short_id = await approved(rig, 1)
    rig.stores.fail_types = {EVENT_SHADOW_CONFIRMED}
    with pytest.raises(ConnectionError):
        press_confirm(h, short_id)
    after = rig.restart()
    report = after.rebuild(T_PRESS + timedelta(minutes=1))
    assert report.restored_reservations == ()
    assert after.positions() == []


async def test_crash_after_the_confirm_is_journaled_still_rebuilds_the_reservation() -> None:
    rig = Rig()
    crashing = CrashingReserve(rig.reservations)
    h, short_id = await approved(rig, 1, reservations=crashing)
    with pytest.raises(RuntimeError):
        press_confirm(h, short_id)
    assert len(types(rig.stores, EVENT_SHADOW_CONFIRMED)) == 1
    assert rig.positions() == []  # this process never reserved
    # The runtime never continues in that state: a restart rebuilds it from SHADOW_CONFIRMED.
    after = rig.restart()
    report = after.rebuild(T_PRESS + timedelta(minutes=1))
    approval_id = h.confirm.get(short_id).approval.approval_id  # type: ignore[union-attr]
    assert report.restored_reservations == (approval_id,)
    assert after.positions() == [("BTCUSDT", "LONG", Decimal("10"))]


async def test_a_repeated_press_finishes_a_reserve_that_did_not_complete() -> None:
    rig = Rig()
    crashing = CrashingReserve(rig.reservations)
    h, short_id = await approved(rig, 1, reservations=crashing)
    with pytest.raises(RuntimeError):
        press_confirm(h, short_id)
    crashing.crash = False
    assert press_confirm(h, short_id, T_PRESS + timedelta(seconds=5)).outcome is (
        ConfirmOutcome.CONFIRMED
    )
    assert len(rig.positions()) == 1
    assert len(h.confirmed) == 1
    assert len(types(rig.stores, EVENT_SHADOW_CONFIRMED)) == 1


async def test_a_restart_before_the_expiry_restores_the_reservation_once() -> None:
    rig = Rig()
    h, short_id = await approved(rig, 1)
    press_confirm(h, short_id)
    before = rig.positions()
    after = rig.restart()
    now = T_PRESS + timedelta(hours=1)
    report = after.rebuild(now)
    assert len(report.restored_reservations) == 1
    assert after.positions(now) == before
    # Replaying the same journal again, on the same or on another process, adds nothing.
    again = after.rebuild(now)
    assert again.restored_reservations == ()
    assert len(after.positions(now)) == 1
    other = rig.restart()
    other.rebuild(now)
    other.rebuild(now)
    assert len(other.positions(now)) == 1


async def test_a_restart_after_the_expiry_restores_nothing_and_records_the_release_once() -> None:
    rig = Rig()
    h, short_id = await approved(rig, 1)
    press_confirm(h, short_id)
    approval_id = h.confirm.get(short_id).approval.approval_id  # type: ignore[union-attr]
    after = rig.restart()
    offline_until = PLAN_EXPIRY + timedelta(minutes=5)
    report = after.rebuild(offline_until)
    assert report.expired_unfilled == (approval_id,)
    assert report.restored_reservations == ()
    assert after.positions(offline_until) == []
    assert after.reservations.positions() == ()  # no late fill, no revived plan
    assert len(types(rig.stores, EVENT_SHADOW_PLAN_EXPIRED_UNFILLED)) == 1
    # A second restart at another clock writes the same event id and payload: no conflict.
    third = rig.restart()
    later = third.rebuild(PLAN_EXPIRY + timedelta(hours=9))
    assert later.restored_reservations == ()
    assert later.already_ended == (approval_id,)
    assert len(types(rig.stores, EVENT_SHADOW_PLAN_EXPIRED_UNFILLED)) == 1
    # And a restart that finds the expiry unrecorded records the identical event (idempotent).
    fourth = rig.restart()
    fourth.rebuild(PLAN_EXPIRY + timedelta(days=2))
    assert len(types(rig.stores, EVENT_SHADOW_PLAN_EXPIRED_UNFILLED)) == 1


async def test_recovery_events_do_not_depend_on_the_restart_clock() -> None:
    first = Rig()
    second = Rig()
    for rig in (first, second):
        h, short_id = await approved(rig, 1)
        press_confirm(h, short_id)
    first.restart().rebuild(PLAN_EXPIRY + timedelta(minutes=1))
    second.restart().rebuild(PLAN_EXPIRY + timedelta(days=30))
    (a,) = types(first.stores, EVENT_SHADOW_PLAN_EXPIRED_UNFILLED)
    (b,) = types(second.stores, EVENT_SHADOW_PLAN_EXPIRED_UNFILLED)
    assert a.journal_event_id == b.journal_event_id
    assert a.payload_json == b.payload_json
    assert a.occurred_at_utc == b.occurred_at_utc


async def test_a_release_for_a_missing_parent_row_is_refused_and_changes_nothing() -> None:
    rig = Rig()
    h, short_id = await approved(rig, 1)
    press_confirm(h, short_id)
    entry = h.confirm.get(short_id)
    assert entry is not None
    (confirmed,) = types(rig.stores, EVENT_SHADOW_CONFIRMED)
    body = json.loads(confirmed.payload_json)
    body["reservation"]["trade_plan_id"] = "f" * 64  # a plan row that does not exist
    orphan = JournalEvent(
        journal_event_id=confirmed.journal_event_id,
        occurred_at_utc=confirmed.occurred_at_utc,
        event_type=confirmed.event_type,
        entity_type=confirmed.entity_type,
        entity_id=confirmed.entity_id,
        correlation_id=confirmed.correlation_id,
        payload_json=json.dumps(body, sort_keys=True, separators=(",", ":")),
    )
    fresh = rig.restart()
    with pytest.raises(ParentRowMissing):
        fresh.reservations.rebuild_from_records(
            [orphan], None, now_utc=PLAN_EXPIRY + timedelta(minutes=1)
        )
    assert fresh.reservations.pending_reservations() == ()


async def test_the_same_release_id_with_a_different_payload_is_a_journal_conflict() -> None:
    rig = Rig()
    h, short_id = await approved(rig, 1)
    press_confirm(h, short_id)
    rig.restart().rebuild(PLAN_EXPIRY + timedelta(minutes=1))
    (confirmed,) = types(rig.stores, EVENT_SHADOW_CONFIRMED)
    body = json.loads(confirmed.payload_json)
    body["reservation"]["plan_expiry_utc"] = (PLAN_EXPIRY + timedelta(hours=1)).isoformat()
    changed = JournalEvent(
        journal_event_id=confirmed.journal_event_id,
        occurred_at_utc=confirmed.occurred_at_utc,
        event_type=confirmed.event_type,
        entity_type=confirmed.entity_type,
        entity_id=confirmed.entity_id,
        correlation_id=confirmed.correlation_id,
        signal_id=confirmed.signal_id,
        trade_plan_id=confirmed.trade_plan_id,
        approval_id=confirmed.approval_id,
        payload_json=json.dumps(body, sort_keys=True, separators=(",", ":")),
    )
    fresh = Rig(rig.stores).restart()
    with pytest.raises(JournalConflict):
        fresh.reservations.rebuild_from_records(
            [changed], None, now_utc=PLAN_EXPIRY + timedelta(hours=2)
        )


async def test_events_of_another_plan_hash_are_a_conflict_and_restore_nothing() -> None:
    rig = Rig()
    h, short_id = await approved(rig, 1)
    press_confirm(h, short_id)
    records = rig.reservations.load_records()
    stray = JournalEvent(
        journal_event_id="shadow-rsv_" + "0" * 64,
        occurred_at_utc=T_PRESS,
        event_type=EVENT_SHADOW_POSITION_OPENED,
        entity_type="ShadowReservation",
        entity_id=records[0].entity_id,
        correlation_id=records[0].correlation_id,
        payload_json=json.dumps({"plan_hash": "9" * 64}),
    )
    fresh = rig.restart()
    report = fresh.reservations.rebuild_from_records(
        [*records, stray], None, now_utc=T_PRESS + timedelta(minutes=1)
    )
    assert report.conflicts != ()
    assert fresh.positions() == []


async def test_repeated_reserve_and_release_create_no_duplicate_state_or_event() -> None:
    rig = Rig()
    h, short_id = await approved(rig, 1)
    press_confirm(h, short_id)
    entry = h.confirm.get(short_id)
    assert entry is not None
    again = rig.reservations.reserve(
        approval=entry.approval,
        signal=entry.signal,
        plan=entry.plan,
        short_id=short_id,
        confirmed_at_utc=T_PRESS,
    )
    assert again.reserved and again.duplicate
    assert len(rig.positions()) == 1
    rig.reservations.release_expired(PLAN_EXPIRY)
    rig.reservations.release_expired(PLAN_EXPIRY)
    assert len(types(rig.stores, EVENT_SHADOW_PLAN_EXPIRED_UNFILLED)) == 1
    # The stable identity of a confirmation is the plan hash plus the approval id.
    assert shadow_ledger.reservation_key("a", "b") == "a:b"


# --------------------------------------------------------------------------- #
# Compatibility of the new events with every fixed-list consumer.
# --------------------------------------------------------------------------- #


def test_the_literals_are_pinned_to_their_source_modules() -> None:
    assert shadow_ledger.EVENT_SHADOW_CONFIRMED == shadow_confirm.EVENT_SHADOW_CONFIRMED
    assert attribution.EVENT_CONFIRMED == shadow_confirm.EVENT_SHADOW_CONFIRMED
    assert CORRELATION_PREFIX + "x" == shadow_confirm._correlation("x")


def test_the_new_events_fit_the_journal_columns_and_are_not_confirm_outcomes() -> None:
    for event_type in RESERVATION_EVENTS:
        assert len(event_type) <= 64  # journal_events.event_type is String(64), no CHECK
        assert event_type not in TERMINAL_CONFIRM_EVENTS
    assert set(RESERVATION_EVENTS) == {
        EVENT_SHADOW_POSITION_OPENED,
        EVENT_SHADOW_PLAN_EXPIRED_UNFILLED,
        EVENT_SHADOW_RESERVATION_REFUSED,
    }
    for event_type in RESERVATION_EVENTS:
        # attribution maps confirm outcomes only: a reservation event is refused loudly.
        with pytest.raises(ValueError, match="not a terminal confirm event"):
            attribute_shadow_outcome(
                ShadowOutcome(approval_action="APPROVE", confirm_event=event_type)
            )


async def test_the_new_events_leave_the_confirm_sweeps_and_invariants_untouched() -> None:
    rig = Rig()
    h, short_id = await approved(rig, 1)
    press_confirm(h, short_id)
    rig.reservations.release_expired(PLAN_EXPIRY)
    late = PLAN_EXPIRY + timedelta(hours=1)
    # Exactly one TERMINAL confirm event per approved plan, however many reservation events exist.
    assert_no_stranded_approvals(rig.stores, late)
    assert h.confirm.expire_due(late) == []
    assert h.confirm.expire_on_restart(late) == []
    # Ids and payloads of the new events are replay-safe JSON within the 128-char id column.
    for event in rig.stores.journal:
        if event.event_type in RESERVATION_EVENTS:
            assert len(event.journal_event_id) <= 128
            json.loads(event.payload_json)
            assert event.correlation_id.startswith(CORRELATION_PREFIX)


def test_the_module_keeps_the_pure_core_boundary() -> None:
    tree = ast.parse(SHADOW_LEDGER_PATH.read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not {m for m in imported if m.startswith(("src.execution", "src.adapters", "telegram"))}
    assert "src.paper.shadow_confirm" not in imported  # no Telegram-facing import


# --------------------------------------------------------------------------- #
# Fill: the reservation becomes the position; rebuild equals an uninterrupted run.
# --------------------------------------------------------------------------- #

CONFIRMED_AT = SIGNAL_CLOSE  # Q-B start = the minute after, 10:00 (the first scripted minute)


class FillRig:
    """The scripted tracer plan driven through the real reservation API."""

    def __init__(self) -> None:
        self.case, self.parsed, self.expected = _tracer()
        self.outcome = _outcome(self.parsed)
        assert self.outcome.signal is not None and self.outcome.trade_plan is not None
        self.signal = self.outcome.signal
        self.plan = self.outcome.trade_plan
        self.approval = Approval(
            approval_id="apr-tracer",
            trade_plan_id=self.plan.trade_plan_id,
            signal_id=self.signal.signal_id,
            action=ApprovalAction.APPROVE,
            result=ApprovalResult.APPROVED,
            status=ApprovalResult.APPROVED,
            approval_token_hash="t" * 64,
            requested_at_utc=SIGNAL_CLOSE,
            acted_at_utc=SIGNAL_CLOSE,
            actor_id="user",
            request_hash=self.plan.plan_hash,
        )
        self.stores = RecordingStores()
        self.eligibility = eligibility_start_for(
            signal_close_utc=SIGNAL_CLOSE,
            plan_expiry_utc=self.plan.expiry_utc,
            confirm_outcome="CONFIRMED",
            confirmed_at_utc=CONFIRMED_AT,
        )

    def build(self) -> tuple[ShadowLedger, ShadowReservations]:
        ledger = ShadowLedger(
            initial_equity=EQUITY,
            parameter_set_params=PARAMS,
            started_at_utc=SIGNAL_CLOSE - timedelta(hours=1),
        )
        basis = ReservationBasis(Decimal(REALIZED_RISK), Decimal(QUANTITY))
        return ledger, ShadowReservations(ledger, self.stores, basis_for=lambda s, p: basis)

    def confirm(self, reservations: ShadowReservations) -> Reservation:
        """CONFIRM through the port: payload, the SHADOW_CONFIRMED event, then the reserve."""
        assert reservations.check(self.signal, self.plan, CONFIRMED_AT) is None
        payload = reservations.confirm_payload(
            approval=self.approval,
            signal=self.signal,
            plan=self.plan,
            short_id="s" * 32,
            confirmed_at_utc=CONFIRMED_AT,
        )
        self.stores.record_journal(
            JournalEvent(
                journal_event_id="shadow-cnf_" + "1" * 64,
                occurred_at_utc=CONFIRMED_AT,
                event_type=EVENT_SHADOW_CONFIRMED,
                entity_type="ShadowConfirm",
                entity_id=self.approval.approval_id,
                correlation_id=f"{CORRELATION_PREFIX}{self.approval.approval_id}",
                payload_json=json.dumps(
                    {"confirmed_at_utc": CONFIRMED_AT.isoformat(), **payload}, sort_keys=True
                ),
            )
        )
        result = reservations.reserve(
            approval=self.approval,
            signal=self.signal,
            plan=self.plan,
            short_id="s" * 32,
            confirmed_at_utc=CONFIRMED_AT,
        )
        assert result.reserved
        (held,) = reservations.pending_reservations()
        return held

    def driver_for(self, record: PositionRecord) -> Any:
        driver = _driver(self.parsed, self.expected)
        eligibility = eligibility_start_for(
            signal_close_utc=SIGNAL_CLOSE,
            plan_expiry_utc=self.plan.expiry_utc,
            confirm_outcome="CONFIRMED",
            confirmed_at_utc=record.reservation.confirmed_at_utc,
        )
        assert driver.open_confirmed(self.outcome, eligibility).opened
        return driver

    def funding(self, _reservation: Reservation) -> FundingHistory:
        return _funding(self.parsed)


WINDOWS = (at(10, 0), at(10, 1), at(10, 30), at(10, 40), DATA_END)


def test_a_fill_turns_the_reservation_into_one_position_without_double_counting() -> None:
    rig = FillRig()
    ledger, reservations = rig.build()
    held = rig.confirm(reservations)
    driver = rig.driver_for(PositionRecord(held, Decimal(QUANTITY), CONFIRMED_AT))
    source = _source(rig.case)
    funding = _funding(rig.parsed)

    driver.advance_to(at(10, 1), source, funding=funding)
    reservations.sync(held.key, driver)

    assert reservations.pending_reservations() == ()
    assert [r.key for r in reservations.positions()] == [held.key]
    assert len(ledger.ledger.exposures) == 1
    assert [e.open_risk for e in ledger.ledger.exposures] == [Decimal(REALIZED_RISK)]
    opened = [e for e in rig.stores.journal if e.event_type == EVENT_SHADOW_POSITION_OPENED]
    assert len(opened) == 1
    assert json.loads(opened[0].payload_json)["fill_quantity"] == QUANTITY
    # Repeating the sync, the open record or an expiry sweep changes nothing.
    reservations.sync(held.key, driver)
    assert not reservations.record_position_opened(
        key=held.key, fill_quantity=Decimal(QUANTITY), opened_at_utc=at(10, 1)
    )
    assert reservations.release_expired(rig.plan.expiry_utc + timedelta(days=1)) == []
    assert len(ledger.ledger.exposures) == 1
    assert [e for e in rig.stores.journal if e.event_type == EVENT_SHADOW_POSITION_OPENED] == opened
    assert [
        e for e in rig.stores.journal if e.event_type == EVENT_SHADOW_PLAN_EXPIRED_UNFILLED
    ] == []
    # The stop-out then frees the exposure and books the loss.
    driver.advance_to(DATA_END, source, funding=funding)
    reservations.sync(held.key, driver)
    assert ledger.ledger.exposures == ()
    assert ledger.initial_equity - ledger.equity == -driver.trade_record().realized_pnl  # type: ignore[operator]


def _uninterrupted(rig: FillRig, source: Any, until: Any) -> ShadowLedger:
    ledger, reservations = rig.build()
    held = rig.confirm(reservations)
    driver = rig.driver_for(PositionRecord(held, Decimal(QUANTITY), CONFIRMED_AT))
    for window in WINDOWS:
        if window > until:
            break
        driver.advance_to(window, source, funding=_funding(rig.parsed))
        reservations.sync(held.key, driver)
    if until not in WINDOWS:
        driver.advance_to(until, source, funding=_funding(rig.parsed))
        reservations.sync(held.key, driver)
    ledger.risk_inputs(until)
    return ledger


@pytest.mark.parametrize("until", [at(10, 30), DATA_END])
def test_rebuild_from_records_equals_an_uninterrupted_run(until: Any) -> None:
    rig = FillRig()
    source = _source(rig.case)
    expected = _uninterrupted(rig, source, until)
    journal = list(rig.stores.journal)
    assert any(e.event_type == EVENT_SHADOW_POSITION_OPENED for e in journal)

    # A new process: a fresh ledger and stores, only the journal records carried over.
    rig2 = FillRig()
    ledger2, reservations2 = rig2.build()
    report = reservations2.rebuild_from_records(
        journal,
        source,
        now_utc=until,
        driver_for=rig2.driver_for,
        funding_for=rig2.funding,
    )
    assert len(report.restored_positions) == 1
    assert ledger2.ledger == expected.ledger
    open_expected = until == at(10, 30)
    assert bool(report.still_open_positions) is open_expected
    # Replaying the same records again changes nothing.
    again = reservations2.rebuild_from_records(
        journal,
        source,
        now_utc=until,
        driver_for=rig2.driver_for,
        funding_for=rig2.funding,
    )
    assert again.restored_positions == ()
    assert ledger2.ledger == expected.ledger


def test_a_hole_in_the_history_is_annotated_and_reported_never_filled() -> None:
    rig = FillRig()
    full = _source(rig.case)
    mark_rows = [
        r for r in rig.case["mark_bars_1m"] if r["open_time_utc"] != at(10, 20).isoformat()
    ]
    assert len(mark_rows) == len(rig.case["mark_bars_1m"]) - 1
    trade = [parse_minute_row(r, kind="trade") for r in rig.case["trade_bars_1m"]]
    mark = [parse_minute_row(r, kind="mark") for r in mark_rows]
    holed = ListMinuteSource({rig.signal.symbol: trade}, {rig.signal.symbol: mark})

    # The uninterrupted run on the holed history defines the note and the bookings.
    ledger, reservations = rig.build()
    held = rig.confirm(reservations)
    driver = rig.driver_for(PositionRecord(held, Decimal(QUANTITY), CONFIRMED_AT))
    driver.advance_to(DATA_END, holed, funding=_funding(rig.parsed))
    reservations.sync(held.key, driver)
    note = driver.state.coverage_note
    assert note, "the lifecycle annotates the hole"
    journal = list(rig.stores.journal)
    assert full is not holed

    rig2 = FillRig()
    ledger2, reservations2 = rig2.build()
    report = reservations2.rebuild_from_records(
        journal,
        holed,
        now_utc=DATA_END,
        driver_for=rig2.driver_for,
        funding_for=rig2.funding,
    )
    assert dict(report.coverage_notes) == {rig.approval.approval_id: note}
    ledger.risk_inputs(DATA_END)
    assert ledger2.ledger == ledger.ledger  # the hole was not filled with invented minutes


def test_open_positions_cannot_be_rebuilt_without_a_driver() -> None:
    rig = FillRig()
    ledger, reservations = rig.build()
    held = rig.confirm(reservations)
    driver = rig.driver_for(PositionRecord(held, Decimal(QUANTITY), CONFIRMED_AT))
    driver.advance_to(at(10, 1), _source(rig.case), funding=_funding(rig.parsed))
    reservations.sync(held.key, driver)
    _ledger2, fresh = rig.build()
    with pytest.raises(ValueError, match="driver_for"):
        fresh.rebuild_from_records(list(rig.stores.journal), None, now_utc=DATA_END)
    assert ledger.equity != EQUITY or ledger.ledger.exposures  # the live ledger kept its state


def test_the_fill_event_kind_is_what_opens_the_position() -> None:
    rig = FillRig()
    _ledger, reservations = rig.build()
    held = rig.confirm(reservations)
    driver = rig.driver_for(PositionRecord(held, Decimal(QUANTITY), CONFIRMED_AT))
    driver.advance_to(DATA_END, _source(rig.case), funding=_funding(rig.parsed))
    kinds: Sequence[str] = [e.kind for e in driver.events]
    assert EVENT_FILL in kinds
