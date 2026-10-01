"""Deterministic, collision-free journal event ids (plan 17-04, D-10, F-412).

Every journal id builder the audit flagged must be a pure function of the
event's content: the same event built twice gets the same id (a replay is a
no-op on the primary key), two different events never share an id.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from src.domain import journal as journal_module

NOW = datetime(2026, 9, 19, 13, 0, 0, tzinfo=UTC)


def correlated_event_id(**kwargs: str) -> str:
    """Late-bound so a missing builder fails each test, not collection."""
    builder: Any = journal_module.correlated_event_id
    result: str = builder(**kwargs)
    return result


class _ListJournal:
    """Minimal JournalLike sink."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)


def _kwargs(**overrides: str) -> dict[str, str]:
    base = {
        "prefix": "cb",
        "correlation_id": "cbq:1",
        "event_type": "CALLBACK_RECEIVED",
        "entity_id": "short:ab",
        "step": "receipt",
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# correlated_event_id
# --------------------------------------------------------------------------- #


def test_correlated_event_id_shape_and_determinism() -> None:
    first = correlated_event_id(**_kwargs())
    second = correlated_event_id(**_kwargs())
    assert first == second
    assert first.startswith("cb_")
    digest = first[len("cb_") :]
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)
    assert len(first) <= 128


def test_correlated_event_id_stable_across_fresh_interpreters() -> None:
    """No clock, no randomness, no per-process salt: a fresh process agrees."""
    code = (
        "from src.domain.journal import correlated_event_id as c;"
        "print(c(prefix='cb', correlation_id='cbq:1', event_type='CALLBACK_RECEIVED',"
        " entity_id='short:ab', step='receipt'))"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        ).stdout.strip()
        for _ in range(2)
    }
    assert outputs == {correlated_event_id(**_kwargs())}


@pytest.mark.parametrize(
    "field",
    ["correlation_id", "event_type", "entity_id", "step"],
)
def test_correlated_event_id_changes_with_each_argument(field: str) -> None:
    base = correlated_event_id(**_kwargs())
    changed = correlated_event_id(**_kwargs(**{field: "other"}))
    assert base != changed


def test_correlated_event_id_prefix_is_part_of_id() -> None:
    assert correlated_event_id(**_kwargs(prefix="cb")) != correlated_event_id(
        **_kwargs(prefix="xx")
    )


def test_correlated_event_id_json_array_material_avoids_concat_collisions() -> None:
    a = correlated_event_id(**_kwargs(correlation_id="ab", event_type="c"))
    b = correlated_event_id(**_kwargs(correlation_id="a", event_type="bc"))
    assert a != b


@pytest.mark.parametrize(
    "field",
    ["prefix", "correlation_id", "event_type", "entity_id", "step"],
)
def test_correlated_event_id_rejects_empty_argument(field: str) -> None:
    with pytest.raises(ValueError):
        correlated_event_id(**_kwargs(**{field: ""}))


# --------------------------------------------------------------------------- #
# SAFE_MODE events
# --------------------------------------------------------------------------- #


def _safe_mode_event(reason: str, now_utc: datetime = NOW) -> Any:
    from src.reconcile.safe_mode import SafeModeController

    sink = _ListJournal()
    controller = SafeModeController(adapter=SimpleNamespace(), journal=sink)
    controller.enter_safe_mode(reason=reason, now_utc=now_utc)
    assert len(sink.events) == 1
    return sink.events[0]


def test_safe_mode_ids_differ_for_different_reasons_at_same_instant() -> None:
    a = _safe_mode_event("positions_diverged")
    b = _safe_mode_event("orders_diverged")
    assert a.occurred_at_utc == b.occurred_at_utc
    assert a.journal_event_id != b.journal_event_id


def test_safe_mode_id_is_stable_for_the_same_event() -> None:
    a = _safe_mode_event("positions_diverged")
    b = _safe_mode_event("positions_diverged")
    assert a.journal_event_id == b.journal_event_id
    assert a.journal_event_id.startswith("safe_mode_")


def test_safe_mode_enter_and_reenter_differ() -> None:
    from src.reconcile.safe_mode import SafeModeController

    sink = _ListJournal()
    controller = SafeModeController(adapter=SimpleNamespace(), journal=sink)
    controller.enter_safe_mode(reason="a", now_utc=NOW)
    controller.enter_safe_mode(reason="b", now_utc=NOW)
    assert len(sink.events) == 2
    assert sink.events[0].journal_event_id != sink.events[1].journal_event_id


# --------------------------------------------------------------------------- #
# Orphan sweeper events
# --------------------------------------------------------------------------- #


def _sweeper() -> Any:
    from src.reconcile.sweeper import OrphanSweeper

    return OrphanSweeper(adapter=SimpleNamespace(), journal=_ListJournal())


def _probe() -> Any:
    return SimpleNamespace(algo_status="NEW", update_time_utc=None)


def test_sweeper_ids_differ_for_different_algo_ids_at_same_millisecond() -> None:
    sweeper = _sweeper()
    a = sweeper._build_pre_image_event(
        symbol="BTCUSDT", client_algo_id="algo-1", probe=_probe(), now_utc=NOW
    )
    b = sweeper._build_pre_image_event(
        symbol="BTCUSDT", client_algo_id="algo-2", probe=_probe(), now_utc=NOW
    )
    assert a.journal_event_id != b.journal_event_id


def test_sweeper_pre_and_post_cancel_differ_for_one_algo_id() -> None:
    sweeper = _sweeper()
    pre = sweeper._build_pre_image_event(
        symbol="BTCUSDT", client_algo_id="algo-1", probe=_probe(), now_utc=NOW
    )
    post = sweeper._build_post_image_event(symbol="BTCUSDT", client_algo_id="algo-1", now_utc=NOW)
    failed = sweeper._build_failure_event(
        symbol="BTCUSDT", client_algo_id="algo-1", reason="boom", now_utc=NOW
    )
    ids = {pre.journal_event_id, post.journal_event_id, failed.journal_event_id}
    assert len(ids) == 3
    for event in (pre, post, failed):
        assert event.journal_event_id.startswith("orphan_sweep_")


def test_sweeper_same_event_built_twice_has_same_id() -> None:
    sweeper = _sweeper()
    a = sweeper._build_post_image_event(symbol="BTCUSDT", client_algo_id="algo-1", now_utc=NOW)
    b = sweeper._build_post_image_event(symbol="BTCUSDT", client_algo_id="algo-1", now_utc=NOW)
    assert a.journal_event_id == b.journal_event_id


# --------------------------------------------------------------------------- #
# Drill outcome events
# --------------------------------------------------------------------------- #


def _drill_event(*, outcome: str, fault: str = "f", now_utc: datetime = NOW) -> Any:
    from src.ops.drills import DRILL_UNPROTECTED, DrillDeclaration, _build_drill_outcome_event

    declaration = DrillDeclaration(
        name=DRILL_UNPROTECTED,
        runbook_section="test",
        inject=lambda: fault,
        assert_outcome=lambda journal, ctx: outcome,
    )
    return _build_drill_outcome_event(
        declaration=declaration, fault=fault, outcome=outcome, now_utc=now_utc
    )


def test_drill_ids_differ_for_different_payloads_at_same_instant() -> None:
    a = _drill_event(outcome="safe_mode_entered")
    b = _drill_event(outcome="no_action")
    assert a.occurred_at_utc == b.occurred_at_utc
    assert a.journal_event_id != b.journal_event_id


def test_drill_id_is_stable_for_the_same_event() -> None:
    a = _drill_event(outcome="safe_mode_entered")
    b = _drill_event(outcome="safe_mode_entered")
    assert a.journal_event_id == b.journal_event_id
    assert a.journal_event_id.startswith("drill_outcome_")
    json.loads(a.payload_json)  # payload unchanged and still valid JSON


# --------------------------------------------------------------------------- #
# Telegram callback ids: replay-stable correlation (D-10, research C7, A10)
# --------------------------------------------------------------------------- #

CHAT_ID = 123
SHORT_ID = "a" * 32
T1 = datetime(2026, 9, 19, 13, 0, 0, tzinfo=UTC)
T2 = datetime(2026, 9, 19, 13, 0, 7, tzinfo=UTC)


def _parsed(kind_prefix: str = "APR") -> Any:
    from src.adapters.telegram_callbacks import parse_callback_data

    return parse_callback_data(f"{kind_prefix}:{SHORT_ID}")


def _dispatch(
    *,
    correlation_id: str,
    callback_at_utc: datetime,
    chat_id: int = CHAT_ID,
    kind_prefix: str = "APR",
) -> list[Any]:
    from src.adapters.telegram_callbacks import dispatch_callback

    events: list[Any] = []
    dispatch_callback(
        _parsed(kind_prefix),
        callback_chat_id=chat_id,
        authorized_chat_id=CHAT_ID,
        callback_at_utc=callback_at_utc,
        raw_token="",
        correlation_id=correlation_id,
        journal_receipt=events.append,
        lookup_by_short_id=lambda short_id: None,
        lookup_by_token_hash=lambda token_hash: None,
        save_atomic=lambda approval, mapping: None,
    )
    return events


def test_redelivery_journals_identical_ids_and_payloads() -> None:
    first = _dispatch(correlation_id="cbq:777", callback_at_utc=T1)
    second = _dispatch(correlation_id="cbq:777", callback_at_utc=T2)
    assert [e.event_type for e in first] == ["CALLBACK_RECEIVED", "CALLBACK_REJECTED"]
    assert [e.journal_event_id for e in first] == [e.journal_event_id for e in second]
    assert [e.payload_json for e in first] == [e.payload_json for e in second]
    assert [e.occurred_at_utc for e in first] == [T1, T1]
    assert [e.occurred_at_utc for e in second] == [T2, T2]


def test_different_correlation_ids_get_different_ids() -> None:
    a = _dispatch(correlation_id="cbq:777", callback_at_utc=T1)
    b = _dispatch(correlation_id="cbq:778", callback_at_utc=T1)
    assert {e.journal_event_id for e in a}.isdisjoint({e.journal_event_id for e in b})


def test_receipt_and_outcome_ids_are_distinct_within_one_delivery() -> None:
    events = _dispatch(correlation_id="cbq:777", callback_at_utc=T1)
    ids = [e.journal_event_id for e in events]
    assert len(set(ids)) == len(ids)
    assert all(i.startswith("cb_") for i in ids)


def test_chat_reject_receipt_id_differs_from_normal_receipt_id() -> None:
    rejected = _dispatch(correlation_id="cbq:777", callback_at_utc=T1, chat_id=999)
    normal = _dispatch(correlation_id="cbq:777", callback_at_utc=T1)
    assert rejected[0].event_type == normal[0].event_type == "CALLBACK_RECEIVED"
    assert rejected[0].journal_event_id != normal[0].journal_event_id


def test_ok_and_rejected_outcomes_for_one_correlation_never_share_an_id() -> None:
    from src.adapters.telegram_callbacks import _journal_outcome
    from src.domain.enums import RejectionReason

    events: list[Any] = []
    parsed = _parsed()
    for ok, reason in (
        (True, None),
        (False, RejectionReason.INVALIDATED),
        (False, RejectionReason.STALE_SETUP),
    ):
        _journal_outcome(
            events.append,
            parsed=parsed,
            ok=ok,
            reason_code=reason,
            callback_at_utc=T1,
            correlation_id="cbq:777",
        )
    ids = [e.journal_event_id for e in events]
    assert len(set(ids)) == 3


def test_no_receipt_or_outcome_payload_has_a_wall_clock_field() -> None:
    for chat_id in (CHAT_ID, 999):
        for event in _dispatch(correlation_id="cbq:777", callback_at_utc=T1, chat_id=chat_id):
            payload = json.loads(event.payload_json)
            assert "received_at_utc" not in payload
            assert "received_at" not in payload


class _FakeQuery:
    def __init__(self, query_id: Any, data: str = f"APR:{SHORT_ID}") -> None:
        self.id = query_id
        self.data = data
        self.message = SimpleNamespace(chat_id=CHAT_ID)

    async def answer(self) -> None:
        return None


class _FakeUpdate:
    def __init__(self, query: _FakeQuery) -> None:
        self.callback_query = query
        self.effective_chat = SimpleNamespace(id=CHAT_ID)


async def _on_callback(query: _FakeQuery, seen: list[str]) -> None:
    from src.adapters.telegram_callbacks import DispatchResult, on_callback

    def fake_dispatch(parsed: Any, **kwargs: Any) -> DispatchResult:
        seen.append(kwargs["correlation_id"])
        return DispatchResult(ok=True, kind=parsed.kind)

    await on_callback(
        _FakeUpdate(query),  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        authorized_chat_id=CHAT_ID,
        binding_context_resolver=lambda sid: None,
        dispatch=fake_dispatch,
        reply_text_fn=None,
    )


async def test_on_callback_correlation_comes_from_callback_query_id() -> None:
    seen: list[str] = []
    await _on_callback(_FakeQuery("777"), seen)
    await _on_callback(_FakeQuery("777"), seen)  # Telegram redelivery
    await _on_callback(_FakeQuery("778"), seen)
    assert seen == ["cbq:777", "cbq:777", "cbq:778"]


@pytest.mark.parametrize("bad_id", ["", None])
async def test_on_callback_rejects_missing_query_id_before_dispatch(bad_id: Any) -> None:
    seen: list[str] = []
    with pytest.raises(ValueError):
        await _on_callback(_FakeQuery(bad_id), seen)
    assert seen == []
