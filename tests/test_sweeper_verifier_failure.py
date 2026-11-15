"""The orphan sweep goes on past a failing position read or journal write (Phase 20 review WR-B5).

`OrphanSweeper.sweep` created both position-verifier calls before awaiting either, awaited them
outside any `try`, and wrote the `already_gone` row without a guard. A verifier that raises (the
reconcile loop's `_position_amount` raises on purpose so an unreadable position never reads as
zero) aborted the whole sweep: orphans already cancelled in the same call vanished from the
report, and the second call's coroutine was left un-awaited. Now each orphan is isolated: the
reads run one after the other, a failing read skips that orphan with a reason code (exception
class only) and a `SWEEP_SKIPPED` row, and a failing `already_gone` row never ends the sweep.

Evidence label: executed tests with the Binance-semantics fake; no network.
"""

from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.execution.order_ids import derive_algo_client_id

from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.reconcile_doubles import RaisingJournal, RecordingJournal

SWEEP_NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
SYMBOL = "BTCUSDT"
PLAN_A = "a" * 64
PLAN_B = "b" * 64
A_ID = derive_algo_client_id(plan_hash=PLAN_A, role="STOP_LOSS")
B_ID = derive_algo_client_id(plan_hash=PLAN_B, role="STOP_LOSS")
ZERO = Decimal("0")


async def _place_leg(fake: BinanceSemanticsFakeAdapter, client_algo_id: str) -> None:
    await fake.place_algo_protective(
        symbol=SYMBOL,
        side="SELL",
        algo_type="CONDITIONAL",
        type="STOP_MARKET",
        position_side="BOTH",
        trigger_price=Decimal("59000"),
        close_position=True,
        quantity=None,
        working_type="MARK_PRICE",
        client_algo_id=client_algo_id,
        reduce_only=None,
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


def _sweeper(fake: Any, journal: Any) -> Any:
    from src.reconcile.sweeper import OrphanSweeper

    return OrphanSweeper(adapter=fake, journal=journal, now_utc=SWEEP_NOW)


def _rows(journal: RecordingJournal, event_type: str) -> list[dict[str, Any]]:
    return [json.loads(e.payload_json) for e in journal.events if e.event_type == event_type]


async def test_a_failing_position_read_skips_that_orphan_and_keeps_the_cancelled_one() -> None:
    fake = BinanceSemanticsFakeAdapter()
    await _place_leg(fake, A_ID)
    await _place_leg(fake, B_ID)
    journal = RecordingJournal()
    reads: list[int] = []

    def verifier(*, symbol: str) -> Decimal:
        reads.append(1)
        if len(reads) <= 2:
            return ZERO  # orphan A: two zero reads
        raise TypeError("TEST_ONLY unreadable position")  # orphan B

    outcome = await _sweeper(fake, journal).sweep(
        _orphan_diff(A_ID, B_ID), position_verifier=verifier
    )

    assert outcome.cancelled == ((SYMBOL, A_ID),)
    assert [(s.client_algo_id, s.reason) for s in outcome.skipped] == [
        (B_ID, "position_read_failed: TypeError")
    ]
    cancels = [c["kwargs"]["client_algo_id"] for c in fake.calls_to("cancel_algo_order")]
    assert cancels == [A_ID]  # B is never cancelled on an unreadable position
    (row,) = _rows(journal, "SWEEP_SKIPPED")
    assert row == {
        "symbol": SYMBOL,
        "client_algo_id": B_ID,
        "reason": "position_read_failed: TypeError",
    }
    assert "unreadable" not in journal.events[-1].payload_json  # class name only, no text


async def test_a_failing_async_read_leaves_no_unawaited_coroutine_and_reads_in_order() -> None:
    fake = BinanceSemanticsFakeAdapter()
    await _place_leg(fake, B_ID)
    journal = RecordingJournal()
    calls: list[int] = []

    async def verifier(*, symbol: str) -> Decimal:
        calls.append(1)
        raise OSError("TEST_ONLY network error")

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # "coroutine ... was never awaited" becomes a failure
        outcome = await _sweeper(fake, journal).sweep(
            _orphan_diff(B_ID), position_verifier=verifier
        )
        import gc

        gc.collect()

    assert calls == [1]  # the second read is never even created once the first failed
    assert outcome.swept_count == 0
    assert [s.reason for s in outcome.skipped] == ["position_read_failed: OSError"]
    assert fake.calls_to("cancel_algo_order") == []


async def test_a_failing_second_read_skips_the_orphan() -> None:
    fake = BinanceSemanticsFakeAdapter()
    await _place_leg(fake, A_ID)
    journal = RecordingJournal()
    reads = iter([ZERO, RuntimeError("TEST_ONLY second read failed")])

    def verifier(*, symbol: str) -> Decimal:
        item = next(reads)
        if isinstance(item, BaseException):
            raise item
        return item

    outcome = await _sweeper(fake, journal).sweep(_orphan_diff(A_ID), position_verifier=verifier)

    assert [s.reason for s in outcome.skipped] == ["position_read_failed: RuntimeError"]
    assert fake.calls_to("cancel_algo_order") == []


async def test_a_failing_already_gone_row_does_not_end_the_sweep() -> None:
    fake = BinanceSemanticsFakeAdapter()
    await _place_leg(fake, B_ID)  # A was never placed: its probe answers found=False
    journal = RaisingJournal()

    def zero(*, symbol: str) -> Decimal:
        return ZERO

    outcome = await _sweeper(fake, journal).sweep(_orphan_diff(A_ID, B_ID), position_verifier=zero)

    assert outcome.already_gone == ((SYMBOL, A_ID),)
    # B was still reached after A's row failed to journal. Its pre-image cannot be journaled, so
    # its cancel is refused (journal-first for the orphan sweeper) and it is reported as skipped.
    assert [s.client_algo_id for s in outcome.skipped] == [B_ID]
    assert journal.attempts >= 2
