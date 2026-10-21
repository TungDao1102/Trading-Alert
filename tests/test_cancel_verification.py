"""A cancel is not counted until Binance shows it (Phase 20, plan 20-11, D-17, F-502).

Binance answers a cancel of an order that is no longer open with -2011 ("unknown order"), and the
adapter maps that answer to `None`, the same value a real cancel returns. For an entry the answer
can mean FILLED. So a cancel result proves nothing: only a query after the cancel does.

Evidence label: executed tests with the Binance-semantics fake and small scripted adapters; no
network, no Binance. The -2011 semantics are [DOC]; manual-close behavior on Binance is
[NOT_TESTED] (Phase 25).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id

from tests.support.ast_guards import float_constructor_calls, wall_clock_calls
from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.reconcile_doubles import RecordingJournal

NOW_UTC = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
PLAN_HASH = "5" * 64
SYMBOL = "BTCUSDT"
ENTRY_ID = derive_client_order_id(plan_hash=PLAN_HASH, role="ENTRY")
SL_ID = derive_algo_client_id(plan_hash=PLAN_HASH, role="STOP_LOSS")
TP1_ID = derive_algo_client_id(plan_hash=PLAN_HASH, role="TAKE_PROFIT_1")
TP2_ID = derive_algo_client_id(plan_hash=PLAN_HASH, role="TAKE_PROFIT_2")
SRC_ROOT = Path(__file__).parent.parent / "src"

QUANTITY = Decimal("0.004")
PRICE = Decimal("60000")


def _phases(journal: RecordingJournal) -> list[tuple[str, str]]:
    return [(e.entity_id, json.loads(e.payload_json)["phase"]) for e in journal.events]


async def _resting_entry(fake: BinanceSemanticsFakeAdapter) -> None:
    await fake.place_entry(
        symbol=SYMBOL,
        side="BUY",
        position_side="BOTH",
        time_in_force="GTC",
        quantity=QUANTITY,
        price=PRICE,
        new_client_order_id=ENTRY_ID,
    )


async def _expire(fake: BinanceSemanticsFakeAdapter, journal: RecordingJournal) -> Any:
    from src.execution.manager import expire_pending_entry

    return await expire_pending_entry(
        plan_hash=PLAN_HASH,
        symbol=SYMBOL,
        adapter=fake,  # type: ignore[arg-type]
        journal=journal,
        now_utc=NOW_UTC,
        trigger_reason="expiry_time",
    )


# --------------------------------------------------------------------------- #
# Task 1 (tracer): expire_pending_entry end to end.
# --------------------------------------------------------------------------- #


async def test_absent_cancel_of_a_filled_entry_is_not_canceled() -> None:
    """D-17, F-502: the entry filled, so the cancel answers absent (None); it was NOT canceled."""
    from src.execution.cancel_verification import CancelVerdict

    fake = BinanceSemanticsFakeAdapter()
    await _resting_entry(fake)
    fake.fill(ENTRY_ID)
    journal = RecordingJournal()

    verdict = await _expire(fake, journal)

    assert verdict is CancelVerdict.FILLED_OR_PARTIAL
    assert [c["method"] for c in fake.calls if c["method"].startswith("cancel")] == [
        "cancel_normal_order"
    ]
    assert fake.calls_to("query_order_by_client")  # the post-cancel query ran
    assert _phases(journal) == [(ENTRY_ID, "pre_cancel"), (ENTRY_ID, "cancel_unverified")]
    payload = json.loads(journal.events[-1].payload_json)
    assert payload["verdict"] == "FILLED_OR_PARTIAL"
    assert payload["observed_status"] == "FILLED"
    assert all(phase != "post_cancel" for _, phase in _phases(journal))


async def test_a_resting_entry_cancel_is_verified_and_journals_post_cancel() -> None:
    from src.execution.cancel_verification import CancelVerdict

    fake = BinanceSemanticsFakeAdapter()
    await _resting_entry(fake)
    journal = RecordingJournal()

    verdict = await _expire(fake, journal)

    assert verdict is CancelVerdict.CANCELED
    assert _phases(journal) == [(ENTRY_ID, "pre_cancel"), (ENTRY_ID, "post_cancel")]
    assert "verdict" not in json.loads(journal.events[-1].payload_json)


async def test_a_partially_filled_entry_that_ends_canceled_is_canceled_not_unknown() -> None:
    """Binance ends a partly filled entry CANCELED with its executed quantity kept (D-17)."""
    from src.execution.cancel_verification import CancelVerdict

    fake = BinanceSemanticsFakeAdapter()
    await _resting_entry(fake)
    fake.fill(ENTRY_ID, quantity=Decimal("0.001"))
    journal = RecordingJournal()

    assert await _expire(fake, journal) is CancelVerdict.CANCELED
    assert fake.positions[SYMBOL] == Decimal("0.001")  # the position it opened stays


async def test_a_failing_post_cancel_query_is_unknown_and_journals_the_error_type_only() -> None:
    from src.execution.cancel_verification import CancelVerdict

    fake = BinanceSemanticsFakeAdapter()
    await _resting_entry(fake)
    fake.fail_next("query_order_by_client", RuntimeError("signature=SECRET-TOKEN-123"))
    journal = RecordingJournal()

    verdict = await _expire(fake, journal)

    assert verdict is CancelVerdict.UNKNOWN
    assert _phases(journal) == [(ENTRY_ID, "pre_cancel"), (ENTRY_ID, "cancel_unverified")]
    event = journal.events[-1]
    payload = json.loads(event.payload_json)
    assert payload["verdict"] == "UNKNOWN"
    assert payload["error_type"] == "RuntimeError"
    assert "SECRET-TOKEN-123" not in event.payload_json


async def test_not_found_right_after_a_cancel_is_unknown_not_proof() -> None:
    """The entry is absent from both books (as after the 3-day retention): UNKNOWN, no claim."""
    from src.execution.cancel_verification import CancelVerdict

    fake = BinanceSemanticsFakeAdapter()  # nothing was ever placed: cancel -> None, query -> absent
    journal = RecordingJournal()

    verdict = await _expire(fake, journal)

    assert verdict is CancelVerdict.UNKNOWN
    assert _phases(journal)[-1] == (ENTRY_ID, "cancel_unverified")


async def test_a_failing_cancel_is_still_journaled_as_cancel_failed_and_reraised() -> None:
    fake = BinanceSemanticsFakeAdapter()
    await _resting_entry(fake)
    fake.fail_next("cancel_normal_order", RuntimeError("network"))
    journal = RecordingJournal()

    with pytest.raises(RuntimeError):
        await _expire(fake, journal)

    assert _phases(journal) == [(ENTRY_ID, "pre_cancel"), (ENTRY_ID, "cancel_failed")]
    assert fake.calls_to("query_order_by_client") == []  # no verification of a failed cancel


# --------------------------------------------------------------------------- #
# The verdict mapping.
# --------------------------------------------------------------------------- #


class _ScriptedAdapter:
    """Answers the two query methods with a scripted probe, or raises."""

    def __init__(self, entry: Any = None, algo: Any = None, boom: BaseException | None = None):
        self._entry, self._algo, self._boom = entry, algo, boom

    async def query_order_by_client(self, *, symbol: str, orig_client_order_id: str) -> Any:
        if self._boom is not None:
            raise self._boom
        return self._entry

    async def query_algo_order_by_client(self, *, client_algo_id: str) -> Any:
        if self._boom is not None:
            raise self._boom
        return self._algo


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("CANCELED", "CANCELED"),
        ("FILLED", "FILLED_OR_PARTIAL"),
        ("PARTIALLY_FILLED", "FILLED_OR_PARTIAL"),
        ("EXPIRED", "GONE_NOT_CANCELED"),
        ("EXPIRED_IN_MATCH", "GONE_NOT_CANCELED"),
        ("NEW", "STILL_OPEN"),
        ("PENDING_CANCEL", "UNKNOWN"),
        ("REJECTED", "UNKNOWN"),
        ("canceled", "UNKNOWN"),
        (None, "UNKNOWN"),
        (7, "UNKNOWN"),
    ],
)
async def test_confirm_entry_cancel_maps_every_status(status: Any, expected: str) -> None:
    from src.execution.cancel_verification import confirm_entry_cancel

    adapter = _ScriptedAdapter(entry=SimpleNamespace(found=True, status=status))
    verdict = await confirm_entry_cancel(adapter, symbol=SYMBOL, client_order_id=ENTRY_ID)
    assert verdict.value == expected


@pytest.mark.parametrize("found", [False, None, "yes", 1])
async def test_confirm_entry_cancel_needs_found_true(found: Any) -> None:
    from src.execution.cancel_verification import CancelVerdict, confirm_entry_cancel

    adapter = _ScriptedAdapter(entry=SimpleNamespace(found=found, status="CANCELED"))
    verdict = await confirm_entry_cancel(adapter, symbol=SYMBOL, client_order_id=ENTRY_ID)
    assert verdict is CancelVerdict.UNKNOWN


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("CANCELED", "CANCELED"),
        ("NEW", "STILL_OPEN"),
        ("TRIGGERING", "GONE_NOT_CANCELED"),
        ("TRIGGERED", "GONE_NOT_CANCELED"),
        ("FINISHED", "GONE_NOT_CANCELED"),
        ("REJECTED", "GONE_NOT_CANCELED"),
        ("EXPIRED", "GONE_NOT_CANCELED"),
        ("SOMETHING_NEW", "UNKNOWN"),
        ("new", "UNKNOWN"),
        (None, "UNKNOWN"),
    ],
)
async def test_confirm_algo_cancel_maps_every_status(status: Any, expected: str) -> None:
    from src.execution.cancel_verification import confirm_algo_cancel

    adapter = _ScriptedAdapter(algo=SimpleNamespace(found=True, algo_status=status))
    verdict = await confirm_algo_cancel(adapter, client_algo_id=SL_ID)
    assert verdict.value == expected


async def test_confirm_algo_cancel_absent_means_nothing_rests_there_not_a_cancel() -> None:
    """No algo order answers to the id: it is gone, but nothing proves WE canceled it."""
    from src.execution.cancel_verification import CancelVerdict, confirm_algo_cancel

    adapter = _ScriptedAdapter(algo=SimpleNamespace(found=False, algo_status=None))
    assert (
        await confirm_algo_cancel(adapter, client_algo_id=SL_ID) is CancelVerdict.GONE_NOT_CANCELED
    )


async def test_confirm_algo_cancel_found_not_a_bool_is_unknown() -> None:
    from src.execution.cancel_verification import CancelVerdict, confirm_algo_cancel

    adapter = _ScriptedAdapter(algo=SimpleNamespace(found=None, algo_status="CANCELED"))
    assert await confirm_algo_cancel(adapter, client_algo_id=SL_ID) is CancelVerdict.UNKNOWN


async def test_confirm_never_raises_and_a_missing_query_method_is_unknown() -> None:
    from src.execution.cancel_verification import (
        CancelDetail,
        CancelVerdict,
        confirm_algo_cancel,
        confirm_entry_cancel,
    )

    boom = _ScriptedAdapter(boom=ConnectionError("https://x/?signature=abc"))
    detail = CancelDetail()
    assert (
        await confirm_entry_cancel(boom, symbol=SYMBOL, client_order_id=ENTRY_ID, detail=detail)
        is CancelVerdict.UNKNOWN
    )
    assert detail.error_type == "ConnectionError"
    assert "signature" not in repr(detail)
    assert await confirm_algo_cancel(boom, client_algo_id=SL_ID) is CancelVerdict.UNKNOWN
    # An adapter without the query method at all (AttributeError) is also UNKNOWN.
    assert await confirm_algo_cancel(object(), client_algo_id=SL_ID) is CancelVerdict.UNKNOWN


async def test_a_cancelled_task_is_not_swallowed_by_confirm() -> None:
    import asyncio

    from src.execution.cancel_verification import confirm_entry_cancel

    adapter = _ScriptedAdapter(boom=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await confirm_entry_cancel(adapter, symbol=SYMBOL, client_order_id=ENTRY_ID)


def test_cancel_verification_reads_no_wall_clock_and_builds_no_float() -> None:
    path = SRC_ROOT / "execution" / "cancel_verification.py"
    assert wall_clock_calls(path) == []
    assert float_constructor_calls(path) == []


# --------------------------------------------------------------------------- #
# Task 3: the sweeper journals every skip and verifies every orphan cancel.
# --------------------------------------------------------------------------- #

SWEEP_NOW = datetime(2026, 10, 21, 11, 0, tzinfo=UTC)


class _StickyCancelFake(BinanceSemanticsFakeAdapter):
    """A cancel of these algo ids is accepted but changes nothing (the leg keeps resting)."""

    def __init__(self) -> None:
        super().__init__()
        self.sticky: set[str] = set()

    async def cancel_algo_order(self, **kwargs: Any) -> Any:
        if kwargs["client_algo_id"] in self.sticky:
            self._bind_real("cancel_algo_order", kwargs)
            self._record_call("cancel_algo_order", kwargs)
            return None
        return await super().cancel_algo_order(**kwargs)


async def _place_leg(fake: BinanceSemanticsFakeAdapter, client_algo_id: str) -> None:
    stop = client_algo_id == SL_ID
    await fake.place_algo_protective(
        symbol=SYMBOL,
        side="SELL",
        algo_type="CONDITIONAL",
        type="STOP_MARKET" if stop else "TAKE_PROFIT_MARKET",
        position_side="BOTH",
        trigger_price=Decimal("59000") if stop else Decimal("61000"),
        close_position=stop,
        quantity=None if stop else QUANTITY / 2,
        working_type="MARK_PRICE",
        client_algo_id=client_algo_id,
        reduce_only=None if stop else True,
    )


def _orphan_diff(*algo_ids: str) -> Any:
    from src.reconcile.compare import CompareDiff, OrphanProtective

    return CompareDiff(
        agreement=False,
        divergences=(),
        orphan_protectives=tuple(
            OrphanProtective(symbol=SYMBOL, client_algo_id=a, order_role="STOP_LOSS")
            for a in algo_ids
        ),
    )


def _flat_verifier(fake: BinanceSemanticsFakeAdapter) -> Any:
    def read(*, symbol: str) -> Decimal:
        return fake.positions.get(symbol, Decimal("0"))

    return read


def _sweeper(fake: Any, journal: Any) -> Any:
    from src.reconcile.sweeper import OrphanSweeper

    return OrphanSweeper(adapter=fake, journal=journal, now_utc=SWEEP_NOW)


def _rows(journal: RecordingJournal, event_type: str) -> list[dict[str, Any]]:
    return [json.loads(e.payload_json) for e in journal.events if e.event_type == event_type]


async def test_a_transient_position_gap_skip_leaves_a_sweep_skipped_row() -> None:
    """IN-14, D-03: a skipped cancel is traced. The row has a reason code, no read values."""
    fake = BinanceSemanticsFakeAdapter()
    await _place_leg(fake, SL_ID)
    reads = iter([Decimal("0.010"), Decimal("0")])
    journal = RecordingJournal()

    outcome = await _sweeper(fake, journal).sweep(
        _orphan_diff(SL_ID), position_verifier=lambda *, symbol: next(reads)
    )

    assert outcome.swept_count == 0 and len(outcome.skipped) == 1
    assert fake.calls_to("cancel_algo_order") == []
    (row,) = _rows(journal, "SWEEP_SKIPPED")
    assert row == {"symbol": SYMBOL, "client_algo_id": SL_ID, "reason": "transient_position_gap"}
    # The existing rule still holds: a skipped cancel writes no ORPHAN_SWEEP row.
    assert _rows(journal, "ORPHAN_SWEEP") == []


async def test_a_failing_sweep_skipped_row_does_not_raise_or_end_the_sweep() -> None:
    from tests.support.reconcile_doubles import RaisingJournal

    fake = BinanceSemanticsFakeAdapter()
    await _place_leg(fake, SL_ID)
    await _place_leg(fake, TP1_ID)
    journal = RaisingJournal()
    reads = iter([Decimal("0.010"), Decimal("0"), Decimal("0.010"), Decimal("0")])

    outcome = await _sweeper(fake, journal).sweep(
        _orphan_diff(SL_ID, TP1_ID), position_verifier=lambda *, symbol: next(reads)
    )

    assert [s.client_algo_id for s in outcome.skipped] == [SL_ID, TP1_ID]  # both were tried
    assert journal.attempts == 2  # one best-effort SWEEP_SKIPPED row each, failures swallowed


async def test_a_failed_probe_and_a_failed_cancel_are_also_traced() -> None:
    fake = BinanceSemanticsFakeAdapter()
    await _place_leg(fake, SL_ID)
    fake.fail_next("query_algo_order_by_client", RuntimeError("https://x/?signature=ab"))
    journal = RecordingJournal()

    def zero(*, symbol: str) -> Decimal:
        return Decimal("0")

    await _sweeper(fake, journal).sweep(_orphan_diff(SL_ID), position_verifier=zero)
    fake.fail_next("cancel_algo_order", RuntimeError("https://x/?signature=cd"))
    await _sweeper(fake, journal).sweep(_orphan_diff(SL_ID), position_verifier=zero)

    reasons = [r["reason"] for r in _rows(journal, "SWEEP_SKIPPED")]
    assert reasons == ["probe_failed: RuntimeError", "cancel_failed: RuntimeError"]
    assert all("signature" not in e.payload_json for e in journal.events)


async def test_an_orphan_cancel_is_verified_and_only_then_swept() -> None:
    from src.execution.cancel_verification import CancelVerdict

    fake = BinanceSemanticsFakeAdapter()
    await _place_leg(fake, SL_ID)
    journal = RecordingJournal()

    outcome = await _sweeper(fake, journal).sweep(
        _orphan_diff(SL_ID), position_verifier=_flat_verifier(fake)
    )

    assert outcome.cancelled == ((SYMBOL, SL_ID),) and outcome.skipped == ()
    assert len(fake.calls_to("query_algo_order_by_client")) == 2  # the probe and the verification
    phases = [json.loads(e.payload_json)["phase"] for e in journal.events]
    assert phases == ["pre_cancel", "post_cancel"]
    assert json.loads(journal.events[-1].payload_json)["verdict"] == CancelVerdict.CANCELED.value
    assert _rows(journal, "SWEEP_SKIPPED") == []


async def test_an_orphan_cancel_that_does_not_take_effect_is_reported_unswept() -> None:
    fake = _StickyCancelFake()
    await _place_leg(fake, SL_ID)
    fake.sticky = {SL_ID}
    journal = RecordingJournal()

    outcome = await _sweeper(fake, journal).sweep(
        _orphan_diff(SL_ID), position_verifier=_flat_verifier(fake)
    )

    assert outcome.swept_count == 0 and outcome.cancelled == ()
    assert [s.reason for s in outcome.skipped] == ["cancel_unverified: STILL_OPEN"]
    payloads = [
        json.loads(e.payload_json) for e in journal.events if e.event_type == "ORPHAN_SWEEP"
    ]
    phases = [p["phase"] for p in payloads]
    assert "post_cancel" not in phases and "cancel_unverified" in phases
    (unverified,) = [p for p in payloads if p["phase"] == "cancel_unverified"]
    assert unverified["verdict"] == "STILL_OPEN" and unverified["observed_status"] == "NEW"
    assert [r["reason"] for r in _rows(journal, "SWEEP_SKIPPED")] == [
        "cancel_unverified: STILL_OPEN"
    ]


async def test_an_orphan_cancel_that_cannot_be_verified_is_reported_unswept() -> None:
    fake = BinanceSemanticsFakeAdapter()
    await _place_leg(fake, SL_ID)
    journal = RecordingJournal()
    # The probe before the cancel works; the verification query after it raises.
    original = fake.query_algo_order_by_client
    seen = {"n": 0}

    async def flaky(**kwargs: Any) -> Any:
        seen["n"] += 1
        if seen["n"] == 2:
            raise ConnectionError("https://x/?signature=ef")
        return await original(**kwargs)

    fake.query_algo_order_by_client = flaky  # type: ignore[method-assign]

    outcome = await _sweeper(fake, journal).sweep(
        _orphan_diff(SL_ID), position_verifier=_flat_verifier(fake)
    )

    assert outcome.cancelled == ()
    assert [s.reason for s in outcome.skipped] == ["cancel_unverified: UNKNOWN"]
    assert all("signature" not in e.payload_json for e in journal.events)
    assert any(
        json.loads(e.payload_json).get("error_type") == "ConnectionError" for e in journal.events
    )


# --- cancel_untriggered_protectives returns the verdicts ---------------------


async def test_cancel_untriggered_protectives_returns_a_verdict_per_leg() -> None:
    from src.execution.cancel_verification import CancelVerdict
    from src.execution.manager import cancel_untriggered_protectives

    fake = BinanceSemanticsFakeAdapter()
    for leg in (SL_ID, TP1_ID, TP2_ID):
        await _place_leg(fake, leg)
    journal = RecordingJournal()

    verdicts = await cancel_untriggered_protectives(
        plan_hash=PLAN_HASH,
        symbol=SYMBOL,
        adapter=fake,  # type: ignore[arg-type]
        journal=journal,
        now_utc=NOW_UTC,
    )

    assert verdicts == {
        "STOP_LOSS": CancelVerdict.CANCELED,
        "TAKE_PROFIT_1": CancelVerdict.CANCELED,
        "TAKE_PROFIT_2": CancelVerdict.CANCELED,
    }
    assert [json.loads(e.payload_json)["phase"] for e in journal.events].count("post_cancel") == 3


async def test_a_lost_stop_on_an_open_position_is_reported_to_the_caller() -> None:
    """A STOP_LOSS verdict GONE_NOT_CANCELED while the position is open is a stop-lost signal.

    The function only reports (the coordinator sweep logs it); it also journals the leg as
    `cancel_unverified`, never as `post_cancel`.
    """
    from src.execution.cancel_verification import CancelVerdict
    from src.execution.manager import cancel_untriggered_protectives

    fake = BinanceSemanticsFakeAdapter()
    await _resting_entry(fake)
    fake.fill(ENTRY_ID)
    await _place_leg(fake, TP1_ID)  # the stop is not there
    journal = RecordingJournal()

    verdicts = await cancel_untriggered_protectives(
        plan_hash=PLAN_HASH,
        symbol=SYMBOL,
        adapter=fake,  # type: ignore[arg-type]
        journal=journal,
        now_utc=NOW_UTC,
    )

    assert fake.positions[SYMBOL] == QUANTITY  # the position is open
    assert verdicts["STOP_LOSS"] is CancelVerdict.GONE_NOT_CANCELED
    assert verdicts["TAKE_PROFIT_1"] is CancelVerdict.CANCELED
    sl_phases = [
        json.loads(e.payload_json)["phase"] for e in journal.events if e.entity_id == SL_ID
    ]
    assert sl_phases == ["pre_cancel", "cancel_unverified"]


async def test_a_failing_leg_cancel_raises_the_group_and_the_other_legs_are_still_verified() -> (
    None
):
    from src.execution.manager import cancel_untriggered_protectives

    fake = BinanceSemanticsFakeAdapter()
    for leg in (SL_ID, TP1_ID, TP2_ID):
        await _place_leg(fake, leg)
    fake.fail_next("cancel_algo_order", RuntimeError("network"))
    journal = RecordingJournal()

    with pytest.raises(ExceptionGroup) as excinfo:
        await cancel_untriggered_protectives(
            plan_hash=PLAN_HASH,
            symbol=SYMBOL,
            adapter=fake,  # type: ignore[arg-type]
            journal=journal,
            now_utc=NOW_UTC,
        )

    assert [type(e) for e in excinfo.value.exceptions] == [RuntimeError]
    assert len(fake.calls_to("query_algo_order_by_client")) == 2  # TP1 and TP2 only
    assert set(fake.open_algos) == {SL_ID}


# --- G4-035: a manual close outside the system, both outcomes (D-28) ----------


async def _manually_closed_position_with_legs(fake: BinanceSemanticsFakeAdapter) -> None:
    await _resting_entry(fake)
    fake.fill(ENTRY_ID)
    for leg in (SL_ID, TP1_ID, TP2_ID):
        await _place_leg(fake, leg)
    fake.positions[SYMBOL] = Decimal("0")  # the operator closed the position on the exchange
    fake.calls.clear()


async def test_manual_close_outside_system_auto_cancel() -> None:
    """Outcome (a), D-28 [NOT_TESTED on Binance]: the exchange cancels the legs by itself.

    The legs read absent (older than the 3-day lookup window), so the sweep finds nothing to
    cancel: no cancel call, no cancel_unverified, no SWEEP_SKIPPED, nothing alarming.
    """
    from datetime import timedelta

    fake = BinanceSemanticsFakeAdapter()
    await _manually_closed_position_with_legs(fake)
    for leg in (SL_ID, TP1_ID, TP2_ID):
        fake.cancel_algo(leg)  # the exchange auto-cancels the legs when the position is flat
    fake.now_utc = fake.now_utc + timedelta(days=4)
    journal = RecordingJournal()

    outcome = await _sweeper(fake, journal).sweep(
        _orphan_diff(SL_ID, TP1_ID, TP2_ID), position_verifier=_flat_verifier(fake)
    )

    assert outcome.swept_count == 0 and outcome.skipped == ()
    assert outcome.already_gone == ((SYMBOL, SL_ID), (SYMBOL, TP1_ID), (SYMBOL, TP2_ID))
    assert fake.calls_to("cancel_algo_order") == []
    phases = {json.loads(e.payload_json)["phase"] for e in journal.events}
    assert phases == {"already_gone"}
    assert _rows(journal, "SWEEP_SKIPPED") == []


async def test_manual_close_outside_system_auto_cancelled_legs_still_queryable_are_calm() -> None:
    """Outcome (a) inside the lookup window: the canceled legs read CANCELED, the sweep is calm."""
    fake = BinanceSemanticsFakeAdapter()
    await _manually_closed_position_with_legs(fake)
    for leg in (SL_ID, TP1_ID, TP2_ID):
        fake.cancel_algo(leg)
    journal = RecordingJournal()

    outcome = await _sweeper(fake, journal).sweep(
        _orphan_diff(SL_ID, TP1_ID, TP2_ID), position_verifier=_flat_verifier(fake)
    )

    assert outcome.skipped == () and outcome.swept_count == 3
    assert _rows(journal, "SWEEP_SKIPPED") == []
    assert all(
        json.loads(e.payload_json)["phase"] in {"pre_cancel", "post_cancel"} for e in journal.events
    )


async def test_manual_close_outside_system_orphan_swept() -> None:
    """Outcome (b), D-28 [NOT_TESTED on Binance]: the legs stay as orphans.

    Two zero position reads per orphan, a cancel, and a verifying query for each leg.
    """
    fake = BinanceSemanticsFakeAdapter()
    await _manually_closed_position_with_legs(fake)
    journal = RecordingJournal()

    outcome = await _sweeper(fake, journal).sweep(
        _orphan_diff(SL_ID, TP1_ID, TP2_ID), position_verifier=_flat_verifier(fake)
    )

    assert outcome.swept_count == 3 and outcome.skipped == ()
    assert fake.open_algos == {}
    assert len(fake.calls_to("cancel_algo_order")) == 3
    assert len(fake.calls_to("query_algo_order_by_client")) == 6  # probe + verification, per leg
    assert _rows(journal, "SWEEP_SKIPPED") == []
