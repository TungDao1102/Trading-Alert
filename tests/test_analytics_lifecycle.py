"""Lifecycle normalizer tests (Phase 10, plan 10-03, D-02/D-05)."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from src.analytics.latency import Leg, build_execution_quality
from src.analytics.lifecycle import (
    LifecyclePath,
    LifecycleRecord,
    LiveLifecycleResult,
    exclude_test_only,
    normalize_backtest_lifecycle,
    normalize_live_lifecycle,
    normalize_paper_lifecycle,
)
from src.analytics.stats import seconds_between
from src.analytics.types import AnalyticsInputError, EvidenceKind, TradeOutcome
from src.backtest.validator import validate_trade_record
from src.domain.approval import Approval
from src.domain.enums import ApprovalAction, ApprovalResult, OrderStatus, SignalStatus
from src.domain.fill import Fill
from src.domain.journal import JournalEvent
from src.domain.order import Order
from src.domain.signal import Signal

from tests.phase10_helpers import (
    D,
    load_expected,
    load_input,
    make_paper_record,
    make_trade_record,
    parse_utc,
)


def _outcome(
    trade_id: str,
    *,
    entry_kind: str | None,
    intended: str | None = None,
    entry: str | None = None,
) -> TradeOutcome:
    return TradeOutcome(
        evidence=EvidenceKind.BACKTEST,
        trade_id=trade_id,
        signal_id=f"SIG-{trade_id}",
        strategy_version="v2.0.0",
        parameter_set_hash="a" * 64,
        symbol="BTCUSDT",
        direction="LONG",
        entry_kind=entry_kind,
        entry_price=None if entry is None else D(entry),
        entry_time_utc=None,
        exit_kind=None,
        exit_price=None,
        exit_time_utc=None,
        quantity=None,
        realized_pnl=None,
        realized_risk=None,
        fallback_applied=False,
        intended_entry_price=None if intended is None else D(intended),
    )


def test_backtest_entry_kind_mapping() -> None:
    outcomes = [
        _outcome("A", entry_kind="ENTRY_FILLED", intended="100", entry="100"),
        _outcome("B", entry_kind="PARTIAL_FILL", intended="100", entry="100"),
        _outcome("C", entry_kind="TOUCH_NO_FILL", intended="100"),
        _outcome("D", entry_kind="EXPIRED", intended="100"),
        _outcome("E", entry_kind="INVALIDATION_CANCEL", intended="100"),
        _outcome("F", entry_kind="DAILY_STOP_CANCEL", intended="100"),
        _outcome("G", entry_kind="PENDING_AT_DATA_END", intended="100"),
    ]
    records = normalize_backtest_lifecycle(outcomes)
    assert [rec.source_id for rec in records] == ["A", "B", "C", "D", "E", "F", "G"]
    assert [rec.entry_filled for rec in records] == [True, True, False, False, False, False, False]
    assert [rec.expired_without_fill for rec in records] == [
        False,
        False,
        False,
        True,
        False,
        False,
        False,
    ]
    for rec in records:
        assert rec.evidence is EvidenceKind.BACKTEST
        assert rec.path is LifecyclePath.SYSTEM_ONLY
        assert rec.signal_detected_at_utc is None
        assert rec.approved_at_utc is None
        assert rec.order_submitted_at_utc is None
        assert rec.fill_time_utc is None
        assert rec.intended_entry_price == D("100")
    assert records[0].actual_entry_price == D("100")
    assert records[2].actual_entry_price is None


def test_backtest_unknown_entry_kind_fails_closed() -> None:
    with pytest.raises(AnalyticsInputError):
        normalize_backtest_lifecycle([_outcome("A", entry_kind="MYSTERY")])


def test_backtest_missing_entry_kind_is_not_an_entry_order() -> None:
    (rec,) = normalize_backtest_lifecycle([_outcome("A", entry_kind=None)])
    assert rec.entry_filled is None
    assert rec.expired_without_fill is None


def test_backtest_duplicate_trade_id_fails_closed() -> None:
    outcomes = [_outcome("A", entry_kind="EXPIRED"), _outcome("A", entry_kind="EXPIRED")]
    with pytest.raises(AnalyticsInputError):
        normalize_backtest_lifecycle(outcomes)


def test_opportunity_skipped_and_expired_rows_are_retained() -> None:
    data = load_input("opportunity_skipped_expired")
    expected = load_expected("opportunity_skipped_expired")
    paper = [make_paper_record(row) for row in data["records"]]
    lifecycle = normalize_paper_lifecycle(paper)
    assert len(lifecycle) == expected["n_records"] == 2
    for rec, want in zip(lifecycle, expected["lifecycle"], strict=True):
        assert rec.signal_id == want["signal_id"]
        assert rec.path is LifecyclePath(want["path"])
        assert rec.approval_result is ApprovalResult(want["approval_result"])
        assert rec.reason_code == want["reason_code"]
        assert rec.approved_at_utc is None
        assert rec.order_submitted_at_utc is None
        assert rec.fill_time_utc is None
        assert rec.synthetic_lag is False

    section = build_execution_quality(lifecycle, evidence=EvidenceKind.PAPER, resamples=100)
    assert section.n_records == 2
    assert section.leg(Leg.SIGNAL_TO_SEEN).incomplete == tuple(
        (r, c) for r, c in expected["seen_incomplete"]
    )
    # They reach no downstream leg denominator.
    downstream = (
        Leg.DELIVERY_TO_APPROVED,
        Leg.SIGNAL_TO_APPROVED,
        Leg.APPROVED_TO_ORDER,
        Leg.ORDER_TO_FILL,
    )
    for leg in downstream:
        stat = section.leg(leg)
        assert stat.n_measured == expected["downstream_legs_n_measured"]
        assert stat.incomplete == ()
    assert section.fill_rate.denominator == expected["fill_rate"]["denominator"]
    assert section.fill_rate.pct is None
    assert section.expiry_rate.pct is None


def test_paper_duplicate_attribution_fails_closed() -> None:
    data = load_input("opportunity_skipped_expired")
    rows = [make_paper_record(row) for row in data["records"]]
    with pytest.raises(AnalyticsInputError):
        normalize_paper_lifecycle([*rows, rows[0]])


# --------------------------------------------------------------------------- #
# Plan 16-36 Task 2: measured delay labels and test_only exclusion (D-15, D-18, REV-03)
# --------------------------------------------------------------------------- #


def _paper_rows() -> list[Any]:
    return [make_paper_record(row) for row in load_input("paper_lifecycle")["records"]]


def _as_shadow_human(rows: list[Any]) -> list[Any]:
    """The user-executed-sim row of SIG-A carries a measured approval request time."""
    out: list[Any] = []
    for row in rows:
        if row.attribution.value == "user-executed-sim":
            row = replace(
                row,
                mode="SHADOW",
                approval_requested_at_utc=parse_utc("2026-02-02T08:00:03+00:00"),
                approval_acted_at_utc=parse_utc("2026-02-02T08:00:50+00:00"),
                order_submitted_at_utc=parse_utc("2026-02-02T08:01:20+00:00"),
                fill_time_utc=parse_utc("2026-02-02T08:07:31+00:00"),
                confirm_requested_at_utc=parse_utc("2026-02-02T08:00:51+00:00"),
                confirmed_at_utc=parse_utc("2026-02-02T08:01:10+00:00"),
            )
        out.append(row)
    return out


def test_a_user_executed_row_with_a_measured_approval_is_not_synthetic_lag() -> None:
    lifecycle = normalize_paper_lifecycle(_as_shadow_human(_paper_rows()))
    sig_a = next(r for r in lifecycle if r.signal_id == "SIG-A")
    assert sig_a.path is LifecyclePath.USER_EXECUTED
    assert sig_a.synthetic_lag is False
    assert sig_a.approved_at_utc == parse_utc("2026-02-02T08:00:50+00:00")
    # The approval request time is the delivery-request proxy, as it is for LIVE evidence.
    assert sig_a.delivery_requested_at_utc == parse_utc("2026-02-02T08:00:03+00:00")
    assert seconds_between(sig_a.signal_detected_at_utc, sig_a.approved_at_utc) == D("50")


def test_a_user_executed_row_without_a_human_action_keeps_the_synthetic_lag() -> None:
    lifecycle = normalize_paper_lifecycle(_paper_rows())
    sig_a = next(r for r in lifecycle if r.signal_id == "SIG-A")
    assert sig_a.path is LifecyclePath.USER_EXECUTED
    assert sig_a.synthetic_lag is True
    assert sig_a.delivery_requested_at_utc is None
    # A SHADOW record with no human action (the SIMULATE leg) is still synthetic.
    simulated = [
        replace(row, mode="SHADOW") if row.attribution.value == "user-executed-sim" else row
        for row in _paper_rows()
    ]
    again = next(r for r in normalize_paper_lifecycle(simulated) if r.signal_id == "SIG-A")
    assert again.synthetic_lag is True


def _with_test_only(rows: list[Any]) -> list[Any]:
    rehearsal = [
        replace(row, signal_id=f"{row.signal_id}-T", mode="SHADOW", test_only=True)
        for row in rows
        if row.signal_id is not None
    ]
    return [*rows, *rehearsal]


def test_exclude_test_only_drops_the_rehearsal_rows_and_counts_them() -> None:
    rows = _paper_rows()
    mixed = _with_test_only(rows)
    kept, excluded = exclude_test_only(mixed)
    assert kept == tuple(rows)
    assert excluded == len(mixed) - len(rows) > 0
    assert exclude_test_only(rows) == (tuple(rows), 0)


def test_the_paper_normalizer_never_sees_a_test_only_row() -> None:
    rows = _paper_rows()
    assert normalize_paper_lifecycle(_with_test_only(rows)) == normalize_paper_lifecycle(rows)


# --------------------------------------------------------------------------- #
# Task 3: live lifecycle normalizer (join accounting, ENTRY_EXPIRY, malformed rows)
# --------------------------------------------------------------------------- #


def _signal(row: dict[str, Any]) -> Signal:
    detected = parse_utc(row["detected_at_utc"])
    return Signal(
        signal_id=row["signal_id"],
        strategy_id="trend-pullback",
        strategy_version="v2.0.0",
        parameter_set_id="PS-1",
        parameter_set_hash="a" * 64,
        symbol="BTCUSDT",
        direction=row["direction"],
        setup_type="pullback",
        source_timeframe="4h",
        source_candle_close_utc=detected,
        detected_at_utc=detected,
        status=SignalStatus.DETECTED,
        expires_at_utc=detected,
    )


def _approval(row: dict[str, Any]) -> Approval:
    result = ApprovalResult(row["result"])
    acted = row["acted_at_utc"]
    return Approval(
        approval_id=row["approval_id"],
        trade_plan_id=row["trade_plan_id"],
        signal_id=row["signal_id"],
        action=ApprovalAction(row["action"]),
        result=result,
        status=result,
        approval_token_hash="t" * 8,
        requested_at_utc=parse_utc(row["requested_at_utc"]),
        acted_at_utc=None if acted is None else parse_utc(acted),
    )


def _order(row: dict[str, Any]) -> Order:
    submitted = parse_utc(row["submitted_at_utc"])
    return Order(
        order_id=row["order_id"],
        trade_plan_id=row["trade_plan_id"],
        position_id=None,
        parent_order_id=None,
        order_role=row["order_role"],
        exchange="BINANCE",
        symbol="BTCUSDT",
        side="BUY",
        position_side="BOTH",
        order_type="LIMIT",
        time_in_force="GTC",
        quantity=Decimal("1"),
        price=None if row["price"] is None else D(row["price"]),
        stop_price=None,
        close_position=False,
        reduce_only=False,
        client_order_id=row["client_order_id"],
        exchange_order_id=None,
        algo_client_id=None,
        exchange_status="NEW",
        local_status=OrderStatus.NEW,
        submitted_at_utc=submitted,
        updated_at_utc=submitted,
    )


def _fill(row: dict[str, Any]) -> Fill:
    return Fill(
        fill_id=row["fill_id"],
        order_id=row["order_id"],
        exchange_trade_id=f"TR-{row['fill_id']}",
        symbol="BTCUSDT",
        side="BUY",
        position_side="BOTH",
        fill_price=D(row["fill_price"]),
        fill_quantity=D(row["fill_quantity"]),
        quote_quantity=Decimal("1"),
        commission=Decimal("0"),
        commission_asset="USDT",
        realized_pnl=Decimal("0"),
        fill_time_utc=parse_utc(row["fill_time_utc"]),
        is_maker=True,
    )


def _event(row: dict[str, Any]) -> JournalEvent:
    return JournalEvent(
        journal_event_id=row["journal_event_id"],
        occurred_at_utc=parse_utc(row["occurred_at_utc"]),
        event_type="ENTRY_EXPIRY",
        entity_type="Order",
        entity_id=row["entity_id"],
        correlation_id="execution_entry_expiry",
        payload_json=row["payload_json"],
    )


class _Live:
    """The live_lifecycle fixture parsed into frozen domain objects."""

    def __init__(self) -> None:
        data = load_input("live_lifecycle")
        self.signals = [_signal(r) for r in data["signals"]]
        self.approvals = [_approval(r) for r in data["approvals"]]
        self.orders = [_order(r) for r in data["orders"]]
        self.fills = [_fill(r) for r in data["fills"]]
        self.events = [_event(r) for r in data["events"]]

    def run(
        self,
        *,
        signals: Sequence[Signal] | None = None,
        approvals: Sequence[Approval] | None = None,
        orders: Sequence[Order] | None = None,
        fills: Sequence[Fill] | None = None,
        events: Sequence[JournalEvent] | None = None,
    ) -> LiveLifecycleResult:
        return normalize_live_lifecycle(
            self.signals if signals is None else signals,
            self.approvals if approvals is None else approvals,
            self.orders if orders is None else orders,
            self.fills if fills is None else fills,
            self.events if events is None else events,
        )


def _by_signal(result: LiveLifecycleResult) -> dict[str, LifecycleRecord]:
    return {rec.source_id: rec for rec in result.records}


def test_live_lifecycle_fixture_records_joins_and_rejections() -> None:
    expected = load_expected("live_lifecycle")
    result = _Live().run()
    assert [rec.signal_id for rec in result.records] == [
        row["signal_id"] for row in expected["records"]
    ]
    for rec, want in zip(result.records, expected["records"], strict=True):
        assert rec.evidence is EvidenceKind.LIVE
        assert rec.path is LifecyclePath(want["path"])
        want_result = want["approval_result"]
        assert rec.approval_result == (None if want_result is None else ApprovalResult(want_result))
        assert rec.direction == want["direction"]
        assert rec.reason_code == want["reason_code"]
        assert rec.entry_filled is want["entry_filled"]
        assert rec.expired_without_fill is want["expired_without_fill"]
        assert rec.synthetic_lag is False
        for name in ("intended_entry_price", "actual_entry_price"):
            want_price = want[name]
            assert getattr(rec, name) == (None if want_price is None else D(want_price))
        if want["wait_to_fill_s"] is not None:
            assert rec.fill_time_utc is not None
            assert rec.order_submitted_at_utc is not None
            wait = seconds_between(rec.order_submitted_at_utc, rec.fill_time_utc)
            assert wait == D(want["wait_to_fill_s"])
    assert [(j.name, j.matched, j.unmatched) for j in result.joins] == [
        (j["name"], j["matched"], j["unmatched"]) for j in expected["joins"]
    ]
    assert result.rejected == tuple((r, c) for r, c in expected["rejected"])


def test_live_delivery_proxy_and_approved_at_only_for_approved() -> None:
    records = _by_signal(_Live().run())
    approved = records["SIG-L1"]
    assert approved.delivery_requested_at_utc == parse_utc("2026-02-04T10:00:05+00:00")
    assert approved.approved_at_utc == parse_utc("2026-02-04T10:00:20+00:00")
    skipped = records["SIG-L3"]
    assert skipped.delivery_requested_at_utc == parse_utc("2026-02-04T12:00:04+00:00")
    assert skipped.approved_at_utc is None
    assert skipped.order_submitted_at_utc is None
    assert records["SIG-L4"].delivery_requested_at_utc is None


def test_live_records_feed_execution_quality_engine() -> None:
    expected = load_expected("live_lifecycle")["section"]
    result = _Live().run()
    section = build_execution_quality(result.records, evidence=EvidenceKind.LIVE, resamples=100)
    assert section.n_records == expected["n_records"] == 4
    assert section.synthetic_lag_seconds is None
    for stat in section.legs:
        want = expected["legs"][stat.leg.value]
        assert stat.n_measured == want["n_measured"], stat.leg.value
        assert stat.incomplete == tuple((r, c) for r, c in want["incomplete"]), stat.leg.value
        if want["mean"] is None:
            assert stat.mean.value is None
        else:
            assert stat.mean.value == D(want["mean"]), stat.leg.value
    assert section.leg(Leg.ORDER_TO_FILL).mean.value == Decimal("360")
    for rate, key in ((section.fill_rate, "fill_rate"), (section.expiry_rate, "expiry_rate")):
        assert (rate.numerator, rate.denominator) == (
            expected[key]["numerator"],
            expected[key]["denominator"],
        )
        assert rate.pct == D(expected[key]["pct"])
    dev = expected["deviation"]
    assert section.deviation.price.mean.n_valued == dev["n_measured"]
    assert section.deviation.price.mean.value == D(dev["mean_price"])
    assert section.deviation.bps.mean.value == D(dev["mean_bps"])
    assert section.deviation.incomplete == tuple((r, c) for r, c in dev["incomplete"])


def test_pre_cancel_and_cancel_failed_do_not_double_count_expiry() -> None:
    live = _Live()
    only_twins = [
        e
        for e in live.events
        if not (e.entity_id == "CID-2" and '"phase":"post_cancel"' in e.payload_json)
    ]
    failed = replace(
        live.events[0],
        journal_event_id="EV-CF",
        payload_json='{"symbol":"BTCUSDT","identifier":"CID-2","phase":"cancel_failed"}',
    )
    result = live.run(events=[*only_twins, failed])
    assert _by_signal(result)["SIG-L2"].expired_without_fill is False
    # Duplicate post_cancel (at-least-once journaling) still counts one expiry, one record.
    dup = replace(live.events[1], journal_event_id="EV-2-DUP")
    result_dup = live.run(events=[*live.events, dup])
    assert len(result_dup.records) == 4
    assert _by_signal(result_dup)["SIG-L2"].expired_without_fill is True
    section = build_execution_quality(result_dup.records, evidence=EvidenceKind.LIVE, resamples=100)
    assert (section.expiry_rate.numerator, section.expiry_rate.denominator) == (1, 2)


def test_filled_order_is_never_expired_without_fill() -> None:
    live = _Live()
    post_cancel_for_filled = replace(
        live.events[1],
        journal_event_id="EV-FILLED",
        entity_id="CID-1",
        payload_json='{"symbol":"BTCUSDT","identifier":"CID-1","phase":"post_cancel"}',
    )
    result = live.run(events=[*live.events, post_cancel_for_filled])
    rec = _by_signal(result)["SIG-L1"]
    assert rec.entry_filled is True
    assert rec.expired_without_fill is False


def test_output_is_identical_when_inputs_are_shuffled() -> None:
    live = _Live()
    baseline = live.run()
    for seed in range(5):
        rng = random.Random(seed)
        shuffled = live.run(
            signals=rng.sample(live.signals, len(live.signals)),
            approvals=rng.sample(live.approvals, len(live.approvals)),
            orders=rng.sample(live.orders, len(live.orders)),
            fills=rng.sample(live.fills, len(live.fills)),
            events=rng.sample(live.events, len(live.events)),
        )
        assert shuffled == baseline
        assert shuffled.digest() == baseline.digest()


def test_malformed_payloads_are_counted_never_fatal() -> None:
    live = _Live()
    good = live.events[1]
    not_json = replace(good, journal_event_id="EV-BAD-1")
    object.__setattr__(not_json, "payload_json", "{not json")  # bypass constructor validation
    not_object = replace(good, journal_event_id="EV-BAD-2", payload_json='["post_cancel"]')
    mismatch = replace(
        good,
        journal_event_id="EV-BAD-3",
        payload_json='{"identifier":"OTHER","phase":"post_cancel"}',
    )
    bad_phase_type = replace(good, journal_event_id="EV-BAD-4", payload_json='{"phase":7}')
    result = live.run(events=[*live.events, not_json, not_object, mismatch, bad_phase_type])
    assert dict(result.rejected) == {"MALFORMED_ROW": 5}  # fixture's 1 + these 4
    assert _by_signal(result)["SIG-L2"].expired_without_fill is True


def test_payload_free_text_is_never_copied_into_output() -> None:
    live = _Live()
    leaky = replace(
        live.events[1],
        journal_event_id="EV-LEAK",
        payload_json=(
            '{"symbol":"BTCUSDT","identifier":"CID-2","phase":"post_cancel",'
            '"trigger_reason":"SECRET-FREE-TEXT","error_message":"api-key=abc123"}'
        ),
    )
    result = live.run(events=[leaky])
    text = repr(result)
    assert "SECRET-FREE-TEXT" not in text
    assert "abc123" not in text


def test_quantity_weighted_actual_entry_price() -> None:
    live = _Live()
    fills = [
        _fill(
            {
                "fill_id": "W1",
                "order_id": "O-1",
                "fill_price": "100",
                "fill_quantity": "1",
                "fill_time_utc": "2026-02-04T10:06:21+00:00",
            }
        ),
        _fill(
            {
                "fill_id": "W2",
                "order_id": "O-1",
                "fill_price": "104",
                "fill_quantity": "3",
                "fill_time_utc": "2026-02-04T10:07:00+00:00",
            }
        ),
    ]
    rec = _by_signal(live.run(fills=fills))["SIG-L1"]
    assert rec.actual_entry_price == Decimal("103")  # (100*1 + 104*3) / 4
    assert rec.fill_time_utc == parse_utc("2026-02-04T10:06:21+00:00")


def test_duplicate_signal_ids_fail_closed() -> None:
    live = _Live()
    with pytest.raises(AnalyticsInputError):
        live.run(signals=[*live.signals, live.signals[0]])


def test_empty_live_inputs_yield_empty_result() -> None:
    result = normalize_live_lifecycle([], [], [], [], [])
    assert result.records == ()
    assert result.rejected == ()
    assert all(j.matched == 0 and j.unmatched == 0 for j in result.joins)


# --------------------------------------------------------------------------- #
# Plan 14-11: the Phase 10 helpers build v2 trade records (D-23 boundary validator).
# --------------------------------------------------------------------------- #


def test_make_trade_record_accepts_every_v2_field_and_parses_decimals_and_datetimes() -> None:
    record = make_trade_record(
        entry_price="100.00",
        entry_time_utc="2026-01-05T10:00:30+00:00",
        quantity="1",
        exit_kind="TP2",
        exit_price="108.00",
        exit_time_utc="2026-01-05T12:00:30+00:00",
        signal_close_utc="2026-01-05T09:59:59.999000+00:00",
        planned_quantity="2",
        tp1_quantity="0.5",
        tp1_price="104.00",
        tp1_time_utc="2026-01-05T11:00:30+00:00",
        resolved_at_utc="2026-01-05T12:00:30+00:00",
        touch_no_fill_count=2,
        gap_through_stop=True,
        constraints_extrapolated=True,
        regime="BULLISH",
        funding_event_count=3,
    )
    assert record.planned_quantity == D("2")
    assert record.tp1_quantity == D("0.5")
    assert record.tp1_price == D("104.00")
    assert record.tp1_time_utc == parse_utc("2026-01-05T11:00:30+00:00")
    assert record.signal_close_utc == parse_utc("2026-01-05T09:59:59.999000+00:00")
    assert record.resolved_at_utc == parse_utc("2026-01-05T12:00:30+00:00")
    assert (record.touch_no_fill_count, record.funding_event_count) == (2, 3)
    assert record.gap_through_stop is True and record.constraints_extrapolated is True
    assert record.regime == "BULLISH"
    validate_trade_record(record)


def test_a_default_filled_record_passes_the_shared_validator() -> None:
    record = make_trade_record(
        entry_price="100.00",
        entry_time_utc="2026-01-05T10:00:30+00:00",
        quantity="1",
        exit_kind="SL",
        exit_price="98.00",
        exit_time_utc="2026-01-05T10:40:30+00:00",
    )
    assert record.signal_close_utc is not None
    assert record.entry_time_utc is not None
    assert record.signal_close_utc < record.entry_time_utc
    assert record.planned_quantity is not None and record.quantity is not None
    assert record.planned_quantity >= record.quantity
    validate_trade_record(record)


def test_a_default_unfilled_record_has_no_signal_close_and_passes_the_validator() -> None:
    record = make_trade_record(entry_kind="EXPIRED")
    assert record.signal_close_utc is None
    assert record.planned_quantity is None
    validate_trade_record(record)
