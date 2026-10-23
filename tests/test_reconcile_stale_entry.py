"""A resting entry that Binance did not expire raises an ALERT only (plan 20-28).

The GTD entry is the only expiry of a never-filled entry, and Binance Demo did not cancel a GTD
order 780 s and 1500 s after `goodTillDate` (evidence `demo-probe-EVIDENCE-20261022T121349Z.json`
and `...T125303Z.json`, both `[DEMO]` observations quoted from the evidence files; nothing here
re-observes them). The reconcile loop therefore watches for an entry order that is still `NEW`
more than the owner grace after its `goodTillDate`, and tells the operator. It is alert only:

  - no SAFE_MODE entry of its own, no cancel (the loop never cancels a normal order), no state
    change of the plan, no placement;
  - the grace is the owner key `reconcile.entry_stale_grace_ms`, kept NOT_CONFIGURED: no number is
    invented, and while it is unset the check is skipped and the skip is journaled (once);
  - the loop knows no `goodTillDate` by itself, so the caller supplies it (`entry_good_till`, plan
    hash to UTC time), as `UnknownEntryResolver` does. A loop built without it does not run the
    check at all.

Evidence label: executed unit tests with fakes; nothing is [DEMO].
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from src.domain.enums import OrderRole
from src.execution.order_ids import derive_client_order_id
from src.ops.alerts import ALERT_EVENTS, AlertSeverity

from tests.support.execution_limits import test_only_execution_limits as make_test_limits
from tests.support.reconcile_doubles import make_open_order, make_plan_protection
from tests.support.reconcile_rig import NOW, Rig, build_rig

H1 = "1" * 64
H2 = "2" * 64
ENTRY_ID = derive_client_order_id(plan_hash=H1, role=OrderRole.ENTRY.value)
STALE_EVENT = "STALE_ENTRY_ORDER"
SKIPPED_ROW = "RECONCILE_STALE_ENTRY_CHECK_SKIPPED"
STALE_ROW = "RECONCILE_STALE_ENTRY"
GRACE_MS = 4747  # the TEST_ONLY value of reconcile.entry_stale_grace_ms


def awaiting_fill(plan_hash: str = H1) -> Any:
    return make_plan_protection(
        plan_hash,
        state="AWAITING_FILL",
        first_fill=False,
        stop_confirmed=False,
        entry_terminal=False,
    )


def resting_entry(status: str = "NEW", plan_hash: str = H1) -> Any:
    entry_id = derive_client_order_id(plan_hash=plan_hash, role=OrderRole.ENTRY.value)
    return make_open_order(entry_id, "BTCUSDT", status=status)


def rig_with(
    *,
    good_till: Any,
    status: str = "NEW",
    limits: Any = None,
    wired: bool = True,
    orders: tuple[Any, ...] | None = None,
) -> Rig:
    kwargs: dict[str, Any] = {
        "plans": (awaiting_fill(),),
        "normal": orders if orders is not None else (resting_entry(status),),
        "limits": limits,
    }
    if wired:
        kwargs["entry_good_till"] = good_till
    return build_rig(**kwargs)


def stale_alerts(rig: Rig) -> list[Any]:
    return [a for a in rig.alerts.alerts if a.event == STALE_EVENT]


def rows(rig: Rig, event_type: str) -> list[dict[str, Any]]:
    return [json.loads(e.payload_json) for e in rig.journal.events if e.event_type == event_type]


def gtd_ago(milliseconds: int) -> datetime:
    return NOW - timedelta(milliseconds=milliseconds)


# --------------------------------------------------------------------------- #
# The contract and the owner key.
# --------------------------------------------------------------------------- #


def test_the_alert_event_is_in_the_closed_ops05_contract_as_high() -> None:
    assert ALERT_EVENTS[STALE_EVENT] is AlertSeverity.HIGH


def test_the_grace_key_is_an_owner_key_that_is_unset_in_the_committed_file() -> None:
    from pathlib import Path

    from src.execution.execution_limits import load_execution_limits

    root = Path(__file__).resolve().parents[1]
    limits = load_execution_limits(root / "config" / "execution" / "execution-limits-v1.toml")

    assert limits.reconcile_entry_stale_grace_ms is None
    assert "reconcile.entry_stale_grace_ms" in limits.unset_alert_only_keys()
    # The alert-only key never keeps the live path refused on its own account.
    assert "reconcile.entry_stale_grace_ms" not in limits.unset_keys()


def test_an_unset_alert_only_key_does_not_block_the_loop_constructor() -> None:
    limits = make_test_limits(reconcile_entry_stale_grace_ms=None)

    limits.require_live_ready()  # does not raise
    build_rig(limits=limits)  # the loop constructor calls require_live_ready


# --------------------------------------------------------------------------- #
# Detection.
# --------------------------------------------------------------------------- #


async def test_an_entry_still_new_past_the_grace_raises_one_alert_and_nothing_else() -> None:
    rig = rig_with(good_till=lambda _plan_hash: gtd_ago(GRACE_MS + 1))

    report = await rig.loop.tick(now_utc=NOW)

    alerts = stale_alerts(rig)
    assert len(alerts) == 1
    assert (alerts[0].subject, alerts[0].symbol, alerts[0].plan_hash) == ("BTCUSDT", "BTCUSDT", H1)
    assert alerts[0].reason == "ENTRY_NOT_EXPIRED_AFTER_GTD"
    assert report.stale_entries == (ENTRY_ID,)
    # Alert only: nothing was cancelled or placed, and the stale entry added no SAFE_MODE reason.
    assert rig.adapter.cancelled_normal == []
    assert rig.adapter.cancelled_algo == []
    assert rig.adapter.forbidden_calls == []
    assert rig.safe_mode.enter_calls == []  # a resting unfilled entry is no divergence (20-31)
    row = rows(rig, STALE_ROW)[0]
    assert row["client_order_id"] == ENTRY_ID
    assert row["plan_hash"] == H1


async def test_exactly_at_the_grace_is_not_stale() -> None:
    rig = rig_with(good_till=lambda _plan_hash: gtd_ago(GRACE_MS))

    report = await rig.loop.tick(now_utc=NOW)

    assert stale_alerts(rig) == []
    assert report.stale_entries == ()


async def test_before_the_good_till_date_is_not_stale() -> None:
    rig = rig_with(good_till=lambda _plan_hash: NOW + timedelta(minutes=5))

    await rig.loop.tick(now_utc=NOW)

    assert stale_alerts(rig) == []


async def test_only_an_order_that_is_still_new_is_judged() -> None:
    rig = rig_with(good_till=lambda _plan_hash: gtd_ago(60_000), status="PARTIALLY_FILLED")

    await rig.loop.tick(now_utc=NOW)

    assert stale_alerts(rig) == []


async def test_a_standing_stale_entry_is_alerted_once_not_every_tick() -> None:
    rig = rig_with(good_till=lambda _plan_hash: gtd_ago(60_000))

    for index in range(4):
        await rig.loop.tick(now_utc=NOW + timedelta(seconds=index))

    assert len(stale_alerts(rig)) == 1
    assert len(rows(rig, STALE_ROW)) == 1


async def test_an_entry_that_leaves_and_returns_is_alerted_again() -> None:
    rig = rig_with(good_till=lambda _plan_hash: gtd_ago(60_000))
    await rig.loop.tick(now_utc=NOW)

    rig.adapter._normal = []
    await rig.loop.tick(now_utc=NOW + timedelta(seconds=1))
    rig.adapter._normal = [resting_entry()]
    await rig.loop.tick(now_utc=NOW + timedelta(seconds=2))

    assert len(stale_alerts(rig)) == 2


async def test_a_foreign_order_and_an_order_of_another_role_are_not_judged() -> None:
    foreign = make_open_order("manual-order-1", "BTCUSDT")
    rig = rig_with(good_till=lambda _plan_hash: gtd_ago(60_000), orders=(foreign,))

    await rig.loop.tick(now_utc=NOW)

    assert stale_alerts(rig) == []


async def test_an_entry_without_a_local_plan_cannot_be_judged() -> None:
    """The good-till source is keyed by plan hash; an exchange entry no local intent owns is
    already a divergence of its own (UNTRACKED_SYSTEM_ORDER) and gets no second alert."""
    rig = build_rig(
        plans=(),
        normal=(resting_entry(),),
        entry_good_till=lambda _plan_hash: gtd_ago(60_000),
    )

    await rig.loop.tick(now_utc=NOW)

    assert stale_alerts(rig) == []


async def test_two_plans_are_judged_independently() -> None:
    # Different symbols so the ownership rule does not interfere.
    plan_b = make_plan_protection(
        H2,
        symbol="ETHUSDT",
        state="AWAITING_FILL",
        first_fill=False,
        stop_confirmed=False,
        entry_terminal=False,
    )
    order_b = make_open_order(
        derive_client_order_id(plan_hash=H2, role=OrderRole.ENTRY.value), "ETHUSDT"
    )
    times = {H1: gtd_ago(60_000), H2: NOW + timedelta(minutes=1)}
    rig = build_rig(
        plans=(awaiting_fill(H1), plan_b),
        normal=(resting_entry(), order_b),
        entry_good_till=lambda plan_hash: times[plan_hash],
    )

    await rig.loop.tick(now_utc=NOW)

    assert [a.plan_hash for a in stale_alerts(rig)] == [H1]


# --------------------------------------------------------------------------- #
# Skipped checks say so.
# --------------------------------------------------------------------------- #


async def test_while_the_grace_is_unset_the_check_is_skipped_and_says_so_once() -> None:
    limits = make_test_limits(reconcile_entry_stale_grace_ms=None)
    rig = rig_with(good_till=lambda _plan_hash: gtd_ago(600_000), limits=limits)

    for index in range(3):
        await rig.loop.tick(now_utc=NOW + timedelta(seconds=index))

    assert stale_alerts(rig) == []
    skipped = rows(rig, SKIPPED_ROW)
    assert skipped == [{"key": "reconcile.entry_stale_grace_ms", "reason": "KEY_NOT_CONFIGURED"}]


async def test_a_loop_without_a_good_till_source_does_not_run_the_check_at_all() -> None:
    rig = rig_with(good_till=None, wired=False)

    await rig.loop.tick(now_utc=NOW)

    assert stale_alerts(rig) == []
    assert rows(rig, SKIPPED_ROW) == []


async def test_an_unknown_good_till_date_is_skipped_and_journaled_once_per_order() -> None:
    rig = rig_with(good_till=lambda _plan_hash: None)

    for index in range(3):
        await rig.loop.tick(now_utc=NOW + timedelta(seconds=index))

    assert stale_alerts(rig) == []
    assert rows(rig, SKIPPED_ROW) == [{"client_order_id": ENTRY_ID, "reason": "GOOD_TILL_UNKNOWN"}]


async def test_a_raising_or_naive_good_till_source_is_an_unknown_date() -> None:
    def raising(_plan_hash: str) -> datetime:
        raise RuntimeError("store down")

    for source in (raising, lambda _plan_hash: datetime(2026, 9, 18, 0, 0)):
        rig = rig_with(good_till=source)

        report = await rig.loop.tick(now_utc=NOW)

        assert stale_alerts(rig) == []
        assert report.outcome == "COMPARED"
        assert rows(rig, SKIPPED_ROW)[0]["reason"] == "GOOD_TILL_UNKNOWN"


async def test_a_raising_alert_sink_does_not_fail_the_tick_and_is_retried_next_tick() -> None:
    rig = rig_with(good_till=lambda _plan_hash: gtd_ago(60_000))
    rig.alerts._fail_with = RuntimeError("telegram down")

    first = await rig.loop.tick(now_utc=NOW)
    rig.alerts._fail_with = None
    second = await rig.loop.tick(now_utc=NOW + timedelta(seconds=1))

    assert first.outcome == "COMPARED"
    assert first.alerts_failed >= 1
    # A stale entry whose alert could not be delivered is reported again, not forgotten.
    assert len(stale_alerts(rig)) == 1
    assert second.stale_entries == (ENTRY_ID,)


# --------------------------------------------------------------------------- #
# The loop stays read-only.
# --------------------------------------------------------------------------- #


def test_the_loop_module_still_calls_no_cancel_and_no_placement() -> None:
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "src" / "reconcile" / "loop.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not {name for name in called if name.startswith(("cancel_", "place_", "new_"))}
