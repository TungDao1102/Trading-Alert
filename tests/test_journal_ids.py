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
