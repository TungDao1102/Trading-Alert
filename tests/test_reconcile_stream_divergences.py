"""Stream divergences and authentication failures in the reconcile tick (plan 20-16, D-04, D-23).

The user-data router's `SINK_FAILURE` divergence and the supervisor's `TASK_DIED` halt become
compare-vocabulary divergences the loop ACTS on (SAFE_MODE plus an alert), not only a log line;
every other stream divergence triggers one targeted REST query of the ids it names, in the same
tick and before the compare. REST is truth. A truth read that fails with AUTH_OR_SIGNATURE
enters SAFE_MODE AUTH_FAILURE and alerts AUTH_FAILURE.

Evidence label: executed unit tests with fakes. The stream source is an injected double, NOT
wired to a running supervisor or router (Phase 24); nothing here touches Binance or Telegram and
nothing is a Demo observation. SDK error classes are constructed locally.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from binance_common.errors import BadRequestError, NetworkError, UnauthorizedError
from src.adapters.binance_userdata_router import StreamDivergenceKind
from src.adapters.binance_userdata_supervisor import REASON_TASK_DIED
from src.domain.enums import OrderRole
from src.execution.order_ids import derive_algo_client_id
from src.reconcile import loop as loop_module
from src.reconcile.classify import POLICY_BY_KIND
from src.reconcile.compare import Divergence
from src.reconcile.loop import (
    ALERT_SINK_FAILED,
    RECONCILE_ACTION_FAILED,
    RECONCILE_READ_FAILED,
    RECONCILE_SKIPPED_GATE,
    RECONCILE_STREAM_QUERY,
    RECONCILE_TICK,
    TICK_COMPARED,
    TICK_READ_FAILED,
    TICK_SKIPPED_GATE,
)

from tests.support.ast_guards import forbidden_imports
from tests.support.reconcile_doubles import (
    FakeGate,
    RecordingAlertSink,
    make_algo_order,
    make_plan_protection,
    make_position,
)
from tests.support.reconcile_rig import (
    NOW,
    FakeStreamItem,
    FakeStreamSource,
    QueryingAdapter,
    Rig,
    build_rig,
)

H1 = "1" * 64
SRC_RECONCILE = Path(__file__).parent.parent / "src" / "reconcile"
ORDER_ID = "web_manual_77"
ALGO_ID = "web_algo_88"
SNAPSHOTS = (
    "snapshot_open_normal_orders",
    "snapshot_open_algo_orders",
    "snapshot_positions",
)


def agreeing_rig_kwargs() -> dict[str, Any]:
    """BTCUSDT tracked (PROTECTED) and the exchange agrees with the coordinator."""
    return {
        "plans": (make_plan_protection(H1, symbol="BTCUSDT", state="PROTECTED"),),
        "algo": (
            make_algo_order(
                derive_algo_client_id(plan_hash=H1, role=OrderRole.STOP_LOSS.value), "BTCUSDT"
            ),
        ),
        "positions": (make_position("BTCUSDT", "0.004"),),
    }


def rig_with(stream: FakeStreamSource, **extra: Any) -> Rig:
    return build_rig(stream=stream, **{**agreeing_rig_kwargs(), **extra})


def sink_failure(**overrides: Any) -> FakeStreamItem:
    fields: dict[str, Any] = {
        "kind": "SINK_FAILURE",
        "symbol": "BTCUSDT",
        "client_order_id": ORDER_ID,
    }
    return FakeStreamItem(**{**fields, **overrides})


# --------------------------------------------------------------------------- #
# Task 2: SINK_FAILURE and TASK_DIED are acted on; the other kinds drive targeted queries.
# --------------------------------------------------------------------------- #


async def test_sink_failure_is_a_divergence_enters_safe_mode_alerts_and_queries_the_order() -> None:
    stream = FakeStreamSource([sink_failure()])
    rig = rig_with(stream)

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_COMPARED
    assert [d.kind for d in report.divergences] == ["STREAM_SINK_FAILURE"]
    divergence = report.divergences[0]
    assert isinstance(divergence, Divergence)
    assert (divergence.symbol, divergence.client_order_id) == ("BTCUSDT", ORDER_ID)
    assert rig.safe_mode.in_safe_mode is True
    assert rig.safe_mode.entered_reason == "STREAM_SINK_FAILURE"
    assert [(a.event, a.subject, a.reason) for a in rig.alerts.alerts] == [
        ("DIVERGENCE", "BTCUSDT", "STREAM_SINK_FAILURE")
    ]
    assert rig.adapter.order_queries == [("BTCUSDT", ORDER_ID)]
    # The query ran in the same tick, before the compare read its snapshots.
    calls = rig.adapter.calls
    assert calls.index("query_order_by_client") < calls.index("snapshot_open_normal_orders")
    assert RECONCILE_TICK in rig.event_types()
    payload = json.loads(rig.journal.events[-1].payload_json)
    assert payload["counts"] == {"STREAM_SINK_FAILURE": 1}
    assert payload["alerts_sent"] == 1


async def test_a_halted_supervisor_is_a_divergence_enters_user_data_stream_halted_and_alerts() -> (
    None
):
    stream = FakeStreamSource(halted=REASON_TASK_DIED)
    rig = rig_with(stream)

    report = await rig.loop.tick(now_utc=NOW)

    # REST is truth: the tick still read all three snapshots and compared.
    assert report.outcome == TICK_COMPARED
    assert report.agreement is True
    for name in SNAPSHOTS:
        assert rig.adapter.count(name) == 1, name
    assert [d.kind for d in report.divergences] == ["STREAM_TASK_DIED"]
    assert report.divergences[0].reason == REASON_TASK_DIED
    assert rig.safe_mode.entered_reason == "USER_DATA_STREAM_HALTED"
    assert [(a.event, a.subject, a.reason) for a in rig.alerts.alerts] == [
        ("STALE_DATA", "USER_DATA", "STREAM_TASK_DIED")
    ]
    assert rig.protection.notified == []


async def test_an_unknown_stream_algo_triggers_one_algo_query_and_no_safe_mode_by_itself() -> None:
    stream = FakeStreamSource(
        [FakeStreamItem(kind="UNKNOWN_STREAM_ALGO", symbol="BTCUSDT", client_algo_id=ALGO_ID)]
    )
    rig = rig_with(stream)

    report = await rig.loop.tick(now_utc=NOW)

    assert rig.adapter.algo_queries == [ALGO_ID]
    assert rig.adapter.order_queries == []
    assert report.divergences == ()
    assert report.agreement is True
    assert rig.safe_mode.enter_calls == []
    assert rig.alerts.alerts == []
    queries = [e for e in rig.journal.events if e.event_type == RECONCILE_STREAM_QUERY]
    assert len(queries) == 1
    row = json.loads(queries[0].payload_json)
    assert row["stream_kind"] == "UNKNOWN_STREAM_ALGO"
    assert row["found"] is False


@pytest.mark.parametrize(
    "kind",
    [
        "STREAM_ANOMALY",
        "STREAM_FILL_TOTAL_MISMATCH",
        "UNKNOWN_STREAM_ORDER",
        "STREAM_ALGO_TERMINAL_FAILED",
    ],
)
async def test_every_other_stream_kind_queries_the_ids_it_names_and_nothing_more(kind: str) -> None:
    stream = FakeStreamSource(
        [
            FakeStreamItem(
                kind=kind, symbol="BTCUSDT", client_order_id=ORDER_ID, client_algo_id=ALGO_ID
            )
        ]
    )
    rig = rig_with(stream)

    report = await rig.loop.tick(now_utc=NOW)

    assert rig.adapter.order_queries == [("BTCUSDT", ORDER_ID)]
    assert rig.adapter.algo_queries == [ALGO_ID]
    assert report.divergences == ()
    assert rig.safe_mode.enter_calls == []
    assert rig.alerts.alerts == []


async def test_the_same_id_named_twice_in_a_tick_is_queried_once() -> None:
    stream = FakeStreamSource([sink_failure(), sink_failure(), sink_failure(client_order_id="x2")])
    rig = rig_with(stream)

    report = await rig.loop.tick(now_utc=NOW)

    assert rig.adapter.order_queries == [("BTCUSDT", ORDER_ID), ("BTCUSDT", "x2")]
    # Each sink failure is still its own divergence and its own alert.
    assert [d.kind for d in report.divergences] == ["STREAM_SINK_FAILURE"] * 3
    assert len(rig.alerts.alerts) == 3


async def test_an_order_id_without_a_symbol_is_not_queried_but_still_acted_on() -> None:
    stream = FakeStreamSource([sink_failure(symbol=None)])
    rig = rig_with(stream)

    report = await rig.loop.tick(now_utc=NOW)

    assert rig.adapter.order_queries == []
    assert [d.kind for d in report.divergences] == ["STREAM_SINK_FAILURE"]
    assert report.divergences[0].symbol == "USER_DATA"
    assert rig.safe_mode.entered_reason == "STREAM_SINK_FAILURE"
    skipped = [
        json.loads(e.payload_json)
        for e in rig.journal.events
        if e.event_type == RECONCILE_STREAM_QUERY
    ]
    assert [row["skipped"] for row in skipped] == ["NO_SYMBOL"]


async def test_a_failed_targeted_query_is_journaled_by_type_and_the_tick_continues() -> None:
    secret = "token=hunter2-do-not-journal"
    adapter = QueryingAdapter(
        **{
            "algo_orders": agreeing_rig_kwargs()["algo"],
            "positions": agreeing_rig_kwargs()["positions"],
            "fail": {"query_order_by_client": RuntimeError(secret)},
        }
    )
    rig = rig_with(FakeStreamSource([sink_failure()]), adapter=adapter)

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_COMPARED
    assert "stream_query" in report.action_failures
    failed = [e for e in rig.journal.events if e.event_type == RECONCILE_ACTION_FAILED]
    assert [json.loads(e.payload_json)["action"] for e in failed] == ["stream_query"]
    assert json.loads(failed[0].payload_json)["error_type"] == "RuntimeError"
    assert all(secret not in e.payload_json for e in rig.journal.events)
    assert rig.safe_mode.entered_reason == "STREAM_SINK_FAILURE"


@pytest.mark.parametrize("reason", ["KEEPALIVE_FAILURES", "RATE_LIMIT_BAN_ACTIVE", "TASK_DIED"])
async def test_any_supervisor_halt_means_the_stream_is_not_trusted(reason: str) -> None:
    rig = rig_with(FakeStreamSource(halted=reason))

    report = await rig.loop.tick(now_utc=NOW)

    assert [d.kind for d in report.divergences] == ["STREAM_TASK_DIED"]
    assert report.divergences[0].reason == reason
    assert rig.safe_mode.entered_reason == "USER_DATA_STREAM_HALTED"


async def test_a_halt_reason_that_is_not_plain_project_text_is_not_journaled_or_alerted() -> None:
    odd = "apikey=XYZ and spaces"
    rig = rig_with(FakeStreamSource(halted=odd))

    report = await rig.loop.tick(now_utc=NOW)

    assert report.divergences[0].reason == "UNKNOWN"
    assert all("XYZ" not in e.payload_json for e in rig.journal.events)
    assert all("XYZ" not in a.reason for a in rig.alerts.alerts)


async def test_a_recovered_supervisor_adds_no_divergence_and_never_exits_safe_mode() -> None:
    stream = FakeStreamSource(halted="TASK_DIED")
    rig = rig_with(stream)
    await rig.loop.tick(now_utc=NOW)
    assert rig.safe_mode.in_safe_mode is True

    stream.halted = None
    later = await rig.loop.tick(now_utc=NOW)

    assert later.divergences == ()
    assert rig.safe_mode.in_safe_mode is True
    assert rig.safe_mode.entered_reason == "USER_DATA_STREAM_HALTED"


async def test_a_failing_stream_source_is_a_halt_fail_closed() -> None:
    secret = "token=hunter2-do-not-journal"
    rig = rig_with(FakeStreamSource(drain_raises=RuntimeError(secret)))

    report = await rig.loop.tick(now_utc=NOW)

    assert [d.kind for d in report.divergences] == ["STREAM_TASK_DIED"]
    assert rig.safe_mode.entered_reason == "USER_DATA_STREAM_HALTED"
    failed = [e for e in rig.journal.events if e.event_type == RECONCILE_ACTION_FAILED]
    assert json.loads(failed[0].payload_json)["action"] == "stream_drain"
    assert all(secret not in e.payload_json for e in rig.journal.events)

    rig = rig_with(FakeStreamSource(halted_raises=RuntimeError(secret)))
    report = await rig.loop.tick(now_utc=NOW)
    assert [d.kind for d in report.divergences] == ["STREAM_TASK_DIED"]
    assert rig.safe_mode.entered_reason == "USER_DATA_STREAM_HALTED"


async def test_a_quiet_stream_changes_nothing() -> None:
    stream = FakeStreamSource()
    rig = rig_with(stream)

    report = await rig.loop.tick(now_utc=NOW)

    assert stream.drain_calls == 1
    assert report.agreement is True
    assert report.divergences == ()
    assert rig.safe_mode.enter_calls == []
    assert rig.alerts.alerts == []
    assert rig.event_types() == [RECONCILE_TICK]


async def test_a_gate_restricted_tick_leaves_the_stream_queue_untouched() -> None:
    class Restriction:
        reason = "IP_BAN_418"

    stream = FakeStreamSource([sink_failure()])
    rig = rig_with(stream, gate=FakeGate(Restriction()))

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_SKIPPED_GATE
    assert stream.drain_calls == 0
    assert len(stream.items) == 1
    assert rig.adapter.calls == []
    assert rig.event_types() == [RECONCILE_SKIPPED_GATE]


async def test_stream_divergences_are_acted_on_even_when_a_truth_read_fails() -> None:
    adapter = QueryingAdapter(
        **{"fail": {"snapshot_positions": NetworkError("boom")}},
    )
    rig = rig_with(FakeStreamSource([sink_failure()]), adapter=adapter)

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_READ_FAILED
    assert [d.kind for d in report.divergences] == ["STREAM_SINK_FAILURE"]
    assert "STREAM_SINK_FAILURE" in rig.safe_mode.enter_calls
    assert "API_DEGRADATION" in rig.safe_mode.enter_calls
    assert [a.event for a in rig.alerts.alerts] == ["DIVERGENCE"]


async def test_a_raising_alert_sink_does_not_lose_the_stream_divergence() -> None:
    sink = RecordingAlertSink(fail_with=RuntimeError("down"))
    rig = rig_with(FakeStreamSource([sink_failure()]), alerts=sink)

    report = await rig.loop.tick(now_utc=NOW)

    assert report.alerts_failed == 1
    assert rig.safe_mode.entered_reason == "STREAM_SINK_FAILURE"
    assert ALERT_SINK_FAILED in rig.event_types()


async def test_a_stream_divergence_and_a_compare_divergence_share_one_tick() -> None:
    from tests.support.reconcile_doubles import make_open_order

    stream = FakeStreamSource([sink_failure()])
    rig = rig_with(stream, normal=(make_open_order("web_manual_9", "ETHUSDT"),))

    report = await rig.loop.tick(now_utc=NOW)

    assert [d.kind for d in report.divergences] == ["STREAM_SINK_FAILURE", "FOREIGN_ORDER"]
    assert report.safe_mode_reasons == ("STREAM_SINK_FAILURE", "FOREIGN_ORDER")
    assert rig.safe_mode.entered_reason == "FOREIGN_ORDER"
    assert report.alerts_sent == 2
    payload = json.loads(rig.journal.events[-1].payload_json)
    assert payload["divergence_count"] == 2
    assert payload["counts"] == {"STREAM_SINK_FAILURE": 1, "FOREIGN_ORDER": 1}


# --------------------------------------------------------------------------- #
# Parity with the adapters (src.reconcile imports no adapter).
# --------------------------------------------------------------------------- #


def test_the_stream_constants_of_the_loop_match_the_adapter_values() -> None:
    assert loop_module.STREAM_KIND_SINK_FAILURE == StreamDivergenceKind.SINK_FAILURE.value
    assert loop_module.STREAM_HALT_TASK_DIED == REASON_TASK_DIED
    assert set(loop_module.STREAM_KINDS) == {kind.value for kind in StreamDivergenceKind}


def test_the_stream_divergence_kinds_have_a_policy() -> None:
    assert POLICY_BY_KIND["STREAM_SINK_FAILURE"].safe_mode_reason == "STREAM_SINK_FAILURE"
    halted = POLICY_BY_KIND["STREAM_TASK_DIED"]
    assert halted.safe_mode_reason == "USER_DATA_STREAM_HALTED"
    assert halted.alert_event == "STALE_DATA"


def test_the_new_alert_names_are_in_the_operational_vocabulary() -> None:
    from src.ops.alerts import ALERT_EVENTS
    from src.reconcile.classify import ALERT_AUTH_FAILURE, ALERT_STALE_DATA

    assert {ALERT_AUTH_FAILURE, ALERT_STALE_DATA} <= set(ALERT_EVENTS)
    assert ALERT_AUTH_FAILURE == "AUTH_FAILURE"


def test_the_loop_and_classify_import_no_adapter() -> None:
    for module in ("loop.py", "classify.py", "feed_freshness.py"):
        assert forbidden_imports(SRC_RECONCILE / module, ["src.adapters", "binance_sdk"]) == []


# --------------------------------------------------------------------------- #
# Task 3: an authentication failure on a truth read is classified, alerted, fail closed.
# --------------------------------------------------------------------------- #


SECRET_MESSAGE = "apikey=XYZ signature=ABC"


def failing_adapter(method: str, exc: BaseException) -> QueryingAdapter:
    kwargs = agreeing_rig_kwargs()
    return QueryingAdapter(
        algo_orders=kwargs["algo"], positions=kwargs["positions"], fail={method: exc}
    )


async def test_auth_failure_on_read_alerts_and_enters_safe_mode() -> None:
    adapter = failing_adapter("snapshot_positions", UnauthorizedError(SECRET_MESSAGE, -2015))
    rig = build_rig(adapter=adapter, plans=agreeing_rig_kwargs()["plans"])

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_READ_FAILED
    assert report.failed_source == "positions"
    assert report.safe_mode_reasons == ("AUTH_FAILURE",)
    assert rig.safe_mode.entered_reason == "AUTH_FAILURE"
    assert [(a.event, a.subject, a.reason) for a in rig.alerts.alerts] == [
        ("AUTH_FAILURE", "SYSTEM", "AUTH_OR_SIGNATURE")
    ]
    failed = [e for e in rig.journal.events if e.event_type == RECONCILE_READ_FAILED]
    assert len(failed) == 1
    payload = json.loads(failed[0].payload_json)
    assert payload == {
        "category": "AUTH_OR_SIGNATURE",
        "error_type": "UnauthorizedError",
        "source": "positions",
    }
    # No compare ran and nothing was cancelled.
    assert report.agreement is None
    assert rig.adapter.cancelled_algo == []


@pytest.mark.parametrize("method", list(SNAPSHOTS))
async def test_an_auth_failure_on_any_of_the_three_truth_reads_is_an_auth_failure(
    method: str,
) -> None:
    adapter = failing_adapter(method, UnauthorizedError(SECRET_MESSAGE, -2015))
    rig = build_rig(adapter=adapter, plans=agreeing_rig_kwargs()["plans"])

    await rig.loop.tick(now_utc=NOW)

    assert rig.safe_mode.entered_reason == "AUTH_FAILURE"
    assert [a.event for a in rig.alerts.alerts] == ["AUTH_FAILURE"]


@pytest.mark.parametrize(
    "exc",
    [NetworkError("down"), BadRequestError(SECRET_MESSAGE, -1021), RuntimeError(SECRET_MESSAGE)],
)
async def test_any_other_read_failure_stays_api_degradation_without_an_auth_alert(
    exc: BaseException,
) -> None:
    adapter = failing_adapter("snapshot_open_algo_orders", exc)
    rig = build_rig(adapter=adapter, plans=agreeing_rig_kwargs()["plans"])

    report = await rig.loop.tick(now_utc=NOW)

    assert report.safe_mode_reasons == ("API_DEGRADATION",)
    assert rig.safe_mode.entered_reason == "API_DEGRADATION"
    assert rig.alerts.alerts == []


async def test_a_raising_error_facts_is_api_degradation_and_never_a_crash() -> None:
    class BrokenFacts(QueryingAdapter):
        @staticmethod
        def error_facts(exc: BaseException) -> Any:
            raise RuntimeError(SECRET_MESSAGE)

    kwargs = agreeing_rig_kwargs()
    adapter = BrokenFacts(
        algo_orders=kwargs["algo"],
        positions=kwargs["positions"],
        fail={"snapshot_positions": UnauthorizedError(SECRET_MESSAGE, -2015)},
    )
    rig = build_rig(adapter=adapter, plans=kwargs["plans"])

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_READ_FAILED
    assert rig.safe_mode.entered_reason == "API_DEGRADATION"
    assert rig.alerts.alerts == []
    payload = json.loads(
        next(e for e in rig.journal.events if e.event_type == RECONCILE_READ_FAILED).payload_json
    )
    assert payload["category"] == "UNCLASSIFIED"


async def test_an_adapter_without_error_facts_is_api_degradation() -> None:
    from tests.support.reconcile_doubles import FakeReconcileAdapter

    kwargs = agreeing_rig_kwargs()
    plain = FakeReconcileAdapter(
        algo_orders=kwargs["algo"],
        positions=kwargs["positions"],
        fail={"snapshot_positions": UnauthorizedError(SECRET_MESSAGE, -2015)},
    )
    rig = build_rig(adapter=plain, plans=kwargs["plans"])  # type: ignore[arg-type]

    await rig.loop.tick(now_utc=NOW)

    assert rig.safe_mode.entered_reason == "API_DEGRADATION"
    assert rig.alerts.alerts == []


async def test_an_exception_message_never_reaches_a_journal_row_or_an_alert() -> None:
    adapter = failing_adapter("snapshot_positions", UnauthorizedError(SECRET_MESSAGE, -2015))
    rig = build_rig(adapter=adapter, plans=agreeing_rig_kwargs()["plans"])

    await rig.loop.tick(now_utc=NOW)

    blob = " ".join(e.payload_json for e in rig.journal.events)
    blob += " ".join(f"{a.event} {a.subject} {a.reason}" for a in rig.alerts.alerts)
    assert "apikey" not in blob
    assert "XYZ" not in blob
    assert "signature" not in blob


async def test_a_raising_alert_sink_on_an_auth_failure_is_journaled_and_safe_mode_holds() -> None:
    adapter = failing_adapter("snapshot_positions", UnauthorizedError(SECRET_MESSAGE, -2015))
    sink = RecordingAlertSink(fail_with=RuntimeError(SECRET_MESSAGE))
    rig = build_rig(adapter=adapter, plans=agreeing_rig_kwargs()["plans"], alerts=sink)

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_READ_FAILED
    assert rig.safe_mode.entered_reason == "AUTH_FAILURE"
    assert ALERT_SINK_FAILED in rig.event_types()
    assert all("XYZ" not in e.payload_json for e in rig.journal.events)
