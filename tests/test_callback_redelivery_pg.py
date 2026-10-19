"""Callback redelivery: journal idempotency and the concurrent delivery race (Phase 17-14).

Telegram delivers callbacks at least once. These tests drive the real dispatch and execution
chain (wiring in `tests/test_approval_replay_pg.py`) against PostgreSQL and count rows:

  - the same `callback_query.id` delivered again writes no new journal row: the receipt and
    outcome ids are pure functions of the correlation id and the step (D-10), and the journal
    store treats the replay as a no-op that keeps the first delivery's `occurred_at_utc`;
  - a rejected delivery and a later valid delivery with another query id are distinct rows;
  - two threads (separate engines) delivering the same APPROVE end with one decision, one
    ENTRY intent and one `place_entry` (D-17, D-26), with and without the in-process
    per-token lock, which is only a latency optimization: the database arbitrates.
"""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from src.approval.mapping import ShortIdMapping
from src.approval.replay import ApprovalAlreadyDecided
from src.domain.approval import Approval
from src.domain.enums import ApprovalResult, RejectionReason
from src.execution.manager import ExecutionOutcome

from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.intent_store_fakes import BarrierBeforeConsume
from tests.test_approval_replay_pg import (
    ENTRY_CLIENT_ID,
    NOW_UTC,
    OK,
    Process,
    decided_approvals,
    deliver,
    dispatch,
    intent_rows,
    process_on,
    scalar,
    seed_parent_chain,
)

RECEIVED = "CALLBACK_RECEIVED"
RESOLVED = "CALLBACK_RESOLVED"
REJECTED = "CALLBACK_REJECTED"
RECONCILIATION_REQUIRED = ExecutionOutcome(is_no_trade=True, reason_code="RECONCILIATION_REQUIRED")
BARRIER_TIMEOUT_SECONDS = 30.0
WRONG_CHAT_ID = 999


def _journal_rows(engine: Engine, correlation_id: str) -> list[tuple[str, str, datetime]]:
    """(journal_event_id, event_type, occurred_at_utc) of one correlation, ordered by type."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT journal_event_id, event_type, occurred_at_utc FROM journal_events "
                "WHERE correlation_id = :c ORDER BY event_type, journal_event_id"
            ),
            {"c": correlation_id},
        ).all()
    return [(str(i), str(t), at) for i, t, at in rows]


def _types(rows: list[tuple[str, str, datetime]]) -> list[str]:
    return [event_type for _id, event_type, _at in rows]


# --------------------------------------------------------------------------- #
# The same query id, delivered again and again.
# --------------------------------------------------------------------------- #


async def test_same_callback_delivered_three_times_leaves_one_receipt_and_one_resolved_row(
    pg_db: str,
) -> None:
    adapter = BinanceSemanticsFakeAdapter()
    query_id = "cbq:3001"
    # Three deliveries of the same tap, each stamped with its own arrival time.
    arrivals = [NOW_UTC, NOW_UTC + timedelta(seconds=5), NOW_UTC + timedelta(seconds=10)]

    with process_on(pg_db) as first_process:
        seed_parent_chain(first_process)
        first = await deliver(first_process, adapter, query_id=query_id, now_utc=arrivals[0])
        assert first.outcome == OK
        adapter.fill(ENTRY_CLIENT_ID)
        first_process.dispose()

    with process_on(pg_db) as restarted:
        second = await deliver(restarted, adapter, query_id=query_id, now_utc=arrivals[1])
        third = await deliver(restarted, adapter, query_id=query_id, now_utc=arrivals[2])

        assert second.outcome == OK and third.outcome == OK
        assert second.dispatch.ok is True and third.dispatch.ok is True
        assert len(adapter.calls_to("place_entry")) == 1

        rows = _journal_rows(restarted.engine, query_id)
        assert _types(rows) == [RECEIVED, RESOLVED]  # exactly one row per step, no duplicates
        # The surviving rows are the FIRST delivery's: a replay never rewrites history.
        assert [at for _id, _type, at in rows] == [arrivals[0], arrivals[0]]
        assert len({row_id for row_id, _type, _at in rows}) == 2
        assert scalar(restarted.engine, "SELECT count(*) FROM journal_events") == 2

        # The decision stayed the first delivery's too.
        assert decided_approvals(restarted.engine) == [("APPROVED", "CONSUMED")]
        assert first.dispatch.approval is not None
        stored = restarted.approvals.get(first.dispatch.approval.approval_id)
        assert stored is not None and stored.acted_at_utc == arrivals[0]


async def test_a_rejected_redelivery_adds_no_row_either(pg_db: str) -> None:
    query_id = "cbq:3002"
    with process_on(pg_db) as proc:
        seed_parent_chain(proc)
        for _delivery in range(3):
            result = dispatch(proc, query_id=query_id, now_utc=NOW_UTC, chat_id=WRONG_CHAT_ID)
            assert result.ok is False
            assert result.reason_code is RejectionReason.INVALIDATED

        rows = _journal_rows(proc.engine, query_id)
        assert _types(rows) == [RECEIVED, REJECTED]
        # The unknown chat never touched the approval row (D-01).
        assert scalar(proc.engine, "SELECT count(*) FROM approvals WHERE status = 'PENDING'") == 1


# --------------------------------------------------------------------------- #
# A rejected delivery, then a valid one with another query id.
# --------------------------------------------------------------------------- #


async def test_rejected_then_valid_delivery_leave_distinct_rows_without_conflict(
    pg_db: str,
) -> None:
    adapter = BinanceSemanticsFakeAdapter()
    rejected_id, valid_id = "cbq:3003", "cbq:3004"

    with process_on(pg_db) as proc:
        seed_parent_chain(proc)

        rejected = dispatch(proc, query_id=rejected_id, now_utc=NOW_UTC, chat_id=WRONG_CHAT_ID)
        assert rejected.ok is False

        valid = await deliver(
            proc, adapter, query_id=valid_id, now_utc=NOW_UTC + timedelta(seconds=3)
        )
        assert valid.dispatch.ok is True
        assert valid.outcome == OK

        rejected_rows = _journal_rows(proc.engine, rejected_id)
        valid_rows = _journal_rows(proc.engine, valid_id)
        assert _types(rejected_rows) == [RECEIVED, REJECTED]
        assert _types(valid_rows) == [RECEIVED, RESOLVED]

        # Four rows, four ids: same short id and entity, different correlation, no conflict.
        ids = [row_id for row_id, _type, _at in rejected_rows + valid_rows]
        assert len(set(ids)) == 4
        assert scalar(proc.engine, "SELECT count(*) FROM journal_events") == 4

        # The rejected receipt is flagged; the valid one is not.
        with proc.engine.connect() as conn:
            payloads = {
                (str(correlation), str(event_type)): json.loads(payload)
                for correlation, event_type, payload in conn.execute(
                    text(
                        "SELECT correlation_id, event_type, payload_json FROM journal_events "
                        "WHERE event_type = 'CALLBACK_RECEIVED'"
                    )
                ).all()
            }
        assert payloads[(rejected_id, RECEIVED)]["chat_gate_rejected"] is True
        assert "chat_gate_rejected" not in payloads[(valid_id, RECEIVED)]

        assert decided_approvals(proc.engine) == [("APPROVED", "CONSUMED")]
        assert len(adapter.calls_to("place_entry")) == 1


# --------------------------------------------------------------------------- #
# Two threads delivering the same APPROVE concurrently.
# --------------------------------------------------------------------------- #


def _race(
    pg_db: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    in_process_lock: bool,
    same_query_id: bool,
) -> tuple[list[Any], BinanceSemanticsFakeAdapter, list[str]]:
    """Two threads, two engines, released together at a barrier before dispatch.

    Without the in-process lock the threads are also held between the token lookup and the
    decision, so BOTH see PENDING and the database alone decides who wins (D-17).
    """
    adapter = BinanceSemanticsFakeAdapter()
    start = threading.Barrier(2)
    between_lookup_and_decision = threading.Barrier(2)
    consume = threading.Barrier(2)
    saves: list[str] = []
    saves_guard = threading.Lock()

    if not in_process_lock:
        # A distinct lock per call: the per-token lock no longer serializes the threads.
        monkeypatch.setattr("src.approval.replay._lock_for_token", lambda _token: threading.Lock())

    with process_on(pg_db) as seeder, process_on(pg_db) as proc_a, process_on(pg_db) as proc_b:
        seed_parent_chain(seeder)

        def worker(proc: Process, query_id: str) -> Any:
            def lookup(token_hash: str) -> Approval | None:
                found = proc.approvals.lookup_by_token_hash(token_hash)
                if not in_process_lock:
                    between_lookup_and_decision.wait(timeout=BARRIER_TIMEOUT_SECONDS)
                return found

            def save(approval: Approval, mapping: ShortIdMapping | None) -> None:
                try:
                    proc.approvals.save_atomic(approval, mapping)
                except ApprovalAlreadyDecided:
                    with saves_guard:
                        saves.append("lost")
                    raise
                with saves_guard:
                    saves.append("won")

            start.wait(timeout=BARRIER_TIMEOUT_SECONDS)
            return asyncio.run(
                deliver(
                    proc,
                    adapter,
                    query_id=query_id,
                    now_utc=NOW_UTC,
                    intent_store=BarrierBeforeConsume(
                        proc.state, barrier=consume, timeout_seconds=BARRIER_TIMEOUT_SECONDS
                    ),
                    lookup_by_token_hash=lookup,
                    save_atomic=save,
                )
            )

        ids = ("cbq:4001", "cbq:4001") if same_query_id else ("cbq:4001", "cbq:4002")
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, proc_a, ids[0]), pool.submit(worker, proc_b, ids[1])]
            deliveries = [f.result(timeout=60) for f in futures]  # no unhandled exception

        _assert_one_decision_one_entry(seeder.engine, adapter)
        journal_counts = [len(_journal_rows(seeder.engine, query_id)) for query_id in set(ids)]
        total_journal = scalar(seeder.engine, "SELECT count(*) FROM journal_events")
        # Same id: one receipt + one resolved. Distinct ids: one pair per delivery.
        assert journal_counts == [2] * len(set(ids))
        assert total_journal == 2 * len(set(ids))
    return deliveries, adapter, saves


def _assert_one_decision_one_entry(engine: Engine, adapter: BinanceSemanticsFakeAdapter) -> None:
    assert len(adapter.calls_to("place_entry")) == 1
    # Plan 19-15 (D-10): the manager writes only the ENTRY row; the stop belongs to the coordinator.
    assert intent_rows(engine) == [("ENTRY", "ACKED")]
    assert decided_approvals(engine) == [("APPROVED", "CONSUMED")]
    assert scalar(engine, "SELECT count(*) FROM approvals") == 1
    assert scalar(engine, "SELECT count(*) FROM execution_intents WHERE role = 'ENTRY'") == 1


@pytest.mark.parametrize("attempt", range(2))
@pytest.mark.parametrize("same_query_id", [True, False], ids=["same_query_id", "two_query_ids"])
@pytest.mark.parametrize("in_process_lock", [True, False], ids=["token_lock", "db_arbiter"])
def test_two_concurrent_deliveries_of_the_same_approve_place_exactly_one_entry(
    pg_db: str,
    monkeypatch: pytest.MonkeyPatch,
    in_process_lock: bool,
    same_query_id: bool,
    attempt: int,
) -> None:
    deliveries, adapter, saves = _race(
        pg_db, monkeypatch, in_process_lock=in_process_lock, same_query_id=same_query_id
    )

    # Both threads resolved to the one stored decision (a replay to the existing approval).
    approvals = [d.dispatch.approval for d in deliveries]
    assert all(d.dispatch.ok is True for d in deliveries)
    assert all(a is not None and a.status is ApprovalResult.APPROVED for a in approvals)
    assert len({(a.approval_id, a.acted_at_utc) for a in approvals if a is not None}) == 1

    # The winner completed; the loser got the stored outcome, or fail-closed
    # RECONCILIATION_REQUIRED while the winner had not finalized yet. Never a second order.
    outcomes = [d.outcome for d in deliveries]
    assert OK in outcomes
    for outcome in outcomes:
        assert outcome in (OK, RECONCILIATION_REQUIRED)
    assert len(adapter.calls_to("place_entry")) == 1

    if not in_process_lock:
        # Both held PENDING between lookup and decision: the database picked one winner.
        assert sorted(saves) == ["lost", "won"]
    else:
        assert saves == ["won"]  # the second delivery found the decision already stored


# --------------------------------------------------------------------------- #
# Negative control: the barrier really overlaps the two deliveries.
# --------------------------------------------------------------------------- #


def test_negative_control_without_the_database_two_deliveries_would_decide_twice(
    pg_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no per-token lock and a store that never refuses, both deliveries would decide.

    The deciding store here records the decision in memory instead of PostgreSQL, so nothing
    arbitrates between the threads: both save. This proves the barrier in `_race` holds both
    deliveries between the lookup and the decision, so `["lost", "won"]` above is not vacuous.
    """
    monkeypatch.setattr("src.approval.replay._lock_for_token", lambda _token: threading.Lock())
    between = threading.Barrier(2)
    decisions: list[Approval] = []
    guard = threading.Lock()

    with process_on(pg_db) as seeder, process_on(pg_db) as proc_a, process_on(pg_db) as proc_b:
        seed_parent_chain(seeder)

        def worker(proc: Process) -> Any:
            def lookup(token_hash: str) -> Approval | None:
                found = proc.approvals.lookup_by_token_hash(token_hash)
                between.wait(timeout=BARRIER_TIMEOUT_SECONDS)
                return found

            def forgetful_save(approval: Approval, _mapping: ShortIdMapping | None) -> None:
                with guard:
                    decisions.append(approval)

            return dispatch(
                proc,
                query_id="cbq:4003",
                now_utc=NOW_UTC,
                lookup_by_token_hash=lookup,
                save_atomic=forgetful_save,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, proc_a), pool.submit(worker, proc_b)]
            results = [f.result(timeout=60) for f in futures]

        assert all(r.ok for r in results)
        assert len(decisions) == 2  # two decisions: only PostgreSQL stops this in the real chain
        assert decided_approvals(seeder.engine) == []  # and nothing was persisted here
