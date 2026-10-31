"""The user-data event router (Phase 18, plan 18-15 Task 2, EXEC-05, EXEC-02, D-05 to D-08).

Every frame is SYNTHETIC (`tests/support/userdata_frames.py`, label `SYNTHETIC_FROM_SDK_MODEL`):
hand-written from the installed SDK models, never captured Binance data. The trailing-stop
ALGO_UPDATE pair (`ia` false, then true) follows the Binance change log of 2026-08-21 as read
on 2026-10-16 (WebFetch summary, docs/SOURCES.md "Facts read for Phase 18"; not verified live).
Passing these tests is not evidence of how live Binance frames behave.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from src.adapters import binance_userdata_router as router_mod
from src.adapters.binance_userdata_events import (
    AccountUpdateEvent,
    StreamAnomaly,
    StreamAnomalyKind,
    parse_stream_message,
    to_fill_event,
)
from src.adapters.binance_userdata_router import (
    ACCOUNT_CONFIG_HINT,
    ALGO_STATUS_DIAGNOSTIC,
    ROUTER_SINK_FAILURE,
    FillSource,
    FillTotalsTracker,
    KnownOrder,
    RouteResult,
    StreamDivergenceKind,
    UserDataRouter,
)
from src.adapters.binance_userdata_supervisor import TrustedEvent
from src.domain.algo_status import ALGO_STATUS_VOCABULARY, AlgoStatusClass, classify_algo_status
from src.domain.enums import OrderRole, OrderStatus
from src.domain.stream_records import STREAM_ANOMALY, EvidenceSource
from src.execution.fill_monitor import FillEvent
from src.ops import redaction

from tests.support.stream_sinks import (
    SINK_NAMES,
    TEST_ONLY_SESSION_ID,
    FakeOrderLookup,
    InjectedJournalFailure,
    RecordingJournal,
    RecordingSinks,
    make_router,
)
from tests.support.userdata_frames import (
    FRAME_LABEL,
    OMIT,
    SYNTHETIC_EVENT_TIME_MS,
    SYNTHETIC_LISTEN_KEY,
    SYNTHETIC_TRANSACTION_TIME_MS,
    account_config_update_frame,
    account_update_frame,
    algo_update_frame,
    conditional_order_trigger_reject_frame,
    grid_update_frame,
    listen_key_expired_frame,
    margin_call_frame,
    order_trade_update_frame,
    strategy_update_frame,
    trade_lite_frame,
)
from tests.support.virtual_time import TEST_ONLY_VIRTUAL_START

T0 = TEST_ONLY_VIRTUAL_START
ORDER_ID = 8_000_000_001  # the frame builder's default exchange order id
CLIENT_ID = "synthetic-entry-0001"  # the frame builder's default client order id
ALGO_CLIENT_ID = "synthetic-sl-0001"  # the frame builder's default client algo id
ENTRY = KnownOrder(
    local_order_id="test-only-local-order-0001",
    client_id=CLIENT_ID,
    symbol="BTCUSDT",
    role=OrderRole.ENTRY,
    local_status=OrderStatus.NEW,
)
STOP = KnownOrder(
    local_order_id="test-only-local-order-0002",
    client_id=ALGO_CLIENT_ID,
    symbol="BTCUSDT",
    role=OrderRole.STOP_LOSS,
    local_status=OrderStatus.NEW,
)
TERMINAL_FAILED_STATUSES = sorted(
    status
    for status in ALGO_STATUS_VOCABULARY
    if classify_algo_status(status) is AlgoStatusClass.TERMINAL_FAILED
)

# Three TRADE frames of one 0.010 order (synthetic): l 0.004 + 0.003 + 0.003, z 0.004/0.007/0.010.
A: dict[str, Any] = {"t": 901, "l": "0.004", "z": "0.004", "X": "PARTIALLY_FILLED"}
B: dict[str, Any] = {"t": 902, "l": "0.003", "z": "0.007", "X": "PARTIALLY_FILLED"}
C: dict[str, Any] = {"t": 903, "l": "0.003", "z": "0.010", "X": "FILLED"}


@pytest.fixture(autouse=True)
def _isolated_redactor() -> Any:
    redaction.clear_runtime_secrets()
    yield
    redaction.clear_runtime_secrets()


class Harness:
    def __init__(
        self,
        *,
        orders: tuple[KnownOrder, ...] = (ENTRY,),
        algos: tuple[KnownOrder, ...] = (STOP,),
        session_id: str = TEST_ONLY_SESSION_ID,
        journal: RecordingJournal | None = None,
    ) -> None:
        self.sinks = RecordingSinks()
        self.journal = journal if journal is not None else RecordingJournal()
        self.router = make_router(
            lookup=FakeOrderLookup.of(orders=orders, algos=algos),
            journal=self.journal,
            sinks=self.sinks,
            clock=lambda: T0,
            session_id=session_id,
        )
        self.results: list[RouteResult] = []

    def route_frame(
        self, frame: dict[str, Any], *, after_gap: bool = False, received_offset_s: int = 0
    ) -> RouteResult:
        received = T0 + timedelta(seconds=received_offset_s)
        outcome = parse_stream_message(frame, observed_at_utc=received)
        result = self.router.route(
            TrustedEvent(
                outcome=outcome, received_at_utc=received, connection_epoch=1, after_gap=after_gap
            )
        )
        self.results.append(result)
        return result

    def total(self, name: str) -> int:
        return sum(getattr(result, name) for result in self.results)

    def anomaly_records(self, kind: str | None = None) -> list[Any]:
        records = self.journal.by_type(STREAM_ANOMALY)
        if kind is None:
            return records
        return [r for r in records if json.loads(r.payload_json)["kind"] == kind]

    def divergence_kinds(self) -> list[StreamDivergenceKind]:
        return [d.kind for d in self.sinks.divergences]


def trade(**overrides: Any) -> dict[str, Any]:
    return order_trade_update_frame(**overrides)


def stream_fill(frame: dict[str, Any]) -> FillEvent:
    outcome = parse_stream_message(frame, observed_at_utc=T0)
    assert not isinstance(outcome, StreamAnomaly)
    fill = to_fill_event(outcome)  # type: ignore[arg-type]
    assert fill is not None
    return fill


def test_frames_are_labelled_synthetic() -> None:
    assert FRAME_LABEL == "SYNTHETIC_FROM_SDK_MODEL"


# --------------------------------------------------------------------------- #
# FillTotalsTracker.
# --------------------------------------------------------------------------- #


def _parsed(frame: dict[str, Any]) -> Any:
    return parse_stream_message(frame, observed_at_utc=T0)


def test_tracker_consistent_sequence_reports_nothing() -> None:
    tracker = FillTotalsTracker()
    for frame in (A, B, C):
        assert tracker.observe(_parsed(trade(**frame))) is None
    assert tracker.unique_total(str(ORDER_ID)) == Decimal("0.010")
    assert tracker.largest_accumulated(str(ORDER_ID)) == Decimal("0.010")


def test_tracker_reports_a_missing_trade_on_the_latest_accumulated_value_once() -> None:
    tracker = FillTotalsTracker()
    assert tracker.observe(_parsed(trade(**A))) is None
    assert tracker.observe(_parsed(trade(**C))) == Decimal("0.010")
    tracker.mark_reported(str(ORDER_ID), Decimal("0.010"))
    # The same accumulated value again is not reported twice.
    assert tracker.observe(_parsed(trade(**C))) is None


def test_tracker_never_reports_an_older_event() -> None:
    tracker = FillTotalsTracker()
    for frame in (A, B, C):
        tracker.observe(_parsed(trade(**frame)))
    # A late duplicate and an older event: accumulated below the largest seen, no check.
    assert tracker.observe(_parsed(trade(**B))) is None
    assert tracker.observe(_parsed(trade(**A))) is None
    # An older event that is itself new (a missed trade arriving late) is not a mismatch either.
    late = FillTotalsTracker()
    late.observe(_parsed(trade(**A)))
    late.observe(_parsed(trade(**B)))
    late.observe(_parsed(trade(**C)))
    assert late.observe(_parsed(trade(t=904, l="0.001", z="0.005"))) is None


def test_tracker_ignores_non_trade_events() -> None:
    tracker = FillTotalsTracker()
    assert tracker.observe(_parsed(trade(x="NEW", X="NEW"))) is None
    assert tracker.largest_accumulated(str(ORDER_ID)) is None


# --------------------------------------------------------------------------- #
# Fill totals through the router: anomaly, divergence, REST fallback.
# --------------------------------------------------------------------------- #


def test_fill_total_mismatch_journals_surfaces_and_calls_the_fallback_once() -> None:
    h = Harness()
    h.sinks.fallback_fills[str(ORDER_ID)] = [stream_fill(trade(**f)) for f in (A, B, C)]

    h.route_frame(trade(**A))
    assert h.sinks.fallback_calls == []
    result = h.route_frame(trade(**C), after_gap=True)

    assert h.sinks.fallback_calls == [str(ORDER_ID)]
    assert result.fallback_calls == 1
    assert result.fallback_fills == 3
    records = h.anomaly_records(StreamAnomalyKind.FILL_TOTAL_MISMATCH.value)
    assert len(records) == 1
    assert records[0].correlation_id == TEST_ONLY_SESSION_ID
    mismatch = [
        d for d in h.sinks.divergences if d.kind is StreamDivergenceKind.STREAM_FILL_TOTAL_MISMATCH
    ]
    assert len(mismatch) == 1
    assert mismatch[0].client_order_id == CLIENT_ID
    assert mismatch[0].anomaly_kind == StreamAnomalyKind.FILL_TOTAL_MISMATCH.value
    assert mismatch[0].after_gap is True
    sources = [routed.source for routed in h.sinks.fills]
    assert (
        sources
        == [FillSource.USER_DATA_EVENT, FillSource.USER_DATA_EVENT] + [FillSource.REST_FALLBACK] * 3
    )
    assert {routed.fill.exchange_trade_id for routed in h.sinks.fills} == {"901", "902", "903"}

    # The same accumulated value again: no second fallback, no second record.
    h.route_frame(trade(**C))
    assert h.sinks.fallback_calls == [str(ORDER_ID)]
    assert len(h.anomaly_records(StreamAnomalyKind.FILL_TOTAL_MISMATCH.value)) == 1


def test_out_of_order_older_events_never_raise_a_false_mismatch() -> None:
    h = Harness()
    for frame in (A, B, C, B, A):
        h.route_frame(trade(**frame))
    assert h.sinks.fallback_calls == []
    assert h.anomaly_records() == []
    assert h.sinks.divergences == []
    assert len(h.sinks.fills) == 5


def test_fallback_is_called_at_most_once_per_order_and_accumulated_value() -> None:
    h = Harness()
    h.route_frame(trade(**C))  # newest first: unknown history, mismatch for z 0.010
    h.route_frame(trade(**C))
    h.route_frame(trade(**A))  # older: no check
    h.route_frame(trade(**B))  # older: no check
    assert h.sinks.fallback_calls == [str(ORDER_ID)]
    assert h.total("fallback_calls") == 1


# --------------------------------------------------------------------------- #
# Order updates: unknown, known, status hints with evidence.
# --------------------------------------------------------------------------- #


def test_unknown_client_order_id_fabricates_nothing() -> None:
    h = Harness(orders=())
    result = h.route_frame(trade(**A), after_gap=True)

    assert result.handled is True
    assert h.sinks.fills == []
    assert h.sinks.exchange_states == []
    assert h.sinks.status_hints == []
    records = h.anomaly_records(StreamAnomalyKind.UNKNOWN_ORDER.value)
    assert len(records) == 1
    payload = json.loads(records[0].payload_json)
    assert payload["field"] == "o.c"
    assert CLIENT_ID not in records[0].payload_json
    assert h.divergence_kinds() == [StreamDivergenceKind.UNKNOWN_STREAM_ORDER]
    divergence = h.sinks.divergences[0]
    assert divergence.client_order_id == CLIENT_ID
    assert divergence.symbol == "BTCUSDT"
    assert divergence.anomaly_kind == StreamAnomalyKind.UNKNOWN_ORDER.value
    assert divergence.payload_sha256 == payload["payload_sha256"]
    assert divergence.after_gap is True


def test_known_trade_gives_exchange_state_hint_with_evidence_and_fill() -> None:
    h = Harness()
    h.route_frame(trade(**A), received_offset_s=5)

    assert len(h.sinks.exchange_states) == 1
    update = h.sinks.exchange_states[0]
    assert update.local_order_id == ENTRY.local_order_id
    assert update.exchange_status == "PARTIALLY_FILLED"
    assert update.exchange_order_id == str(ORDER_ID)
    assert update.now_utc == T0
    # Phase 24 (24-19): the exchange event time E rides along for the monotonic order guard.
    assert update.exchange_event_time_utc is not None
    assert update.exchange_event_time_utc.utcoffset() == timedelta(0)

    assert len(h.sinks.status_hints) == 1
    hint = h.sinks.status_hints[0]
    assert hint.known == ENTRY
    assert hint.execution_type == "TRADE"
    assert hint.exchange_status == "PARTIALLY_FILLED"
    assert hint.terminal_not_filled is False
    assert hint.evidence.source is EvidenceSource.USER_DATA_EVENT
    assert hint.evidence.reference == f"TRADE:{ORDER_ID}:901"
    assert hint.evidence.correlation_id == TEST_ONLY_SESSION_ID
    assert hint.evidence.observed_at_utc == T0 + timedelta(seconds=5)
    assert len(h.sinks.fills) == 1
    assert h.journal.events == {}


@pytest.mark.parametrize(
    ("execution_type", "order_status"),
    [("CANCELED", "CANCELED"), ("EXPIRED", "EXPIRED"), ("EXPIRED", "EXPIRED_IN_MATCH")],
)
def test_terminal_not_filled_status_gives_a_hint_and_no_fill(
    execution_type: str, order_status: str
) -> None:
    h = Harness()
    h.route_frame(trade(x=execution_type, X=order_status, l="0", z="0"))

    assert h.sinks.fills == []
    assert len(h.sinks.status_hints) == 1
    hint = h.sinks.status_hints[0]
    assert hint.terminal_not_filled is True
    assert hint.exchange_status == order_status
    assert hint.evidence.reference == f"{execution_type}:{ORDER_ID}:none"
    assert [u.exchange_status for u in h.sinks.exchange_states] == [order_status]


def test_new_status_gives_a_non_terminal_hint_and_no_fill() -> None:
    h = Harness()
    h.route_frame(trade(x="NEW", X="NEW", l="0", z="0"))
    assert h.sinks.fills == []
    assert [hint.terminal_not_filled for hint in h.sinks.status_hints] == [False]


def test_trade_with_zero_last_quantity_gives_no_fill() -> None:
    h = Harness()
    h.route_frame(trade(l="0", z="0"))
    assert h.sinks.fills == []
    assert len(h.sinks.status_hints) == 1


# --------------------------------------------------------------------------- #
# ALGO_UPDATE: class, terminal-failed divergence, rm diagnostic.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("status", sorted(ALGO_STATUS_VOCABULARY))
def test_known_algo_reaches_the_algo_sink_with_its_ratified_class(status: str) -> None:
    h = Harness()
    h.route_frame(algo_update_frame(X=status), after_gap=True)

    assert len(h.sinks.algo_routes) == 1
    route = h.sinks.algo_routes[0]
    assert route.known == STOP
    assert route.status_class is classify_algo_status(status)
    assert route.after_gap is True
    expected = (
        [StreamDivergenceKind.STREAM_ALGO_TERMINAL_FAILED]
        if status in TERMINAL_FAILED_STATUSES
        else []
    )
    assert h.divergence_kinds() == expected
    if expected:
        divergence = h.sinks.divergences[0]
        assert divergence.client_algo_id == ALGO_CLIENT_ID
        assert divergence.after_gap is True
    assert h.anomaly_records() == []


def test_terminal_failed_statuses_are_the_documented_defaults() -> None:
    assert TERMINAL_FAILED_STATUSES == ["EXPIRED", "REJECTED"]


def test_unknown_algo_id_gives_anomaly_and_divergence_and_no_algo_route() -> None:
    h = Harness(algos=())
    h.route_frame(algo_update_frame())

    assert h.sinks.algo_routes == []
    records = h.anomaly_records(StreamAnomalyKind.UNKNOWN_ORDER.value)
    assert len(records) == 1
    assert json.loads(records[0].payload_json)["field"] == "o.caid"
    assert h.divergence_kinds() == [StreamDivergenceKind.UNKNOWN_STREAM_ALGO]
    assert h.sinks.divergences[0].client_algo_id == ALGO_CLIENT_ID


def test_reject_reason_is_journaled_as_a_scrubbed_capped_diagnostic() -> None:
    secret = "TestOnlySecretValue123"
    redaction.register_runtime_secret(secret)
    reason = (f"Synthetic reject {secret} " + "x" * 300)[:200]
    h = Harness()
    h.route_frame(algo_update_frame(X="REJECTED", rm=reason))

    diagnostics = h.journal.by_type(ALGO_STATUS_DIAGNOSTIC)
    assert len(diagnostics) == 1
    payload = json.loads(diagnostics[0].payload_json)
    assert secret not in diagnostics[0].payload_json
    assert "[REDACTED]" in payload["reject_reason"]
    assert len(payload["reject_reason"]) <= 200
    assert payload["algo_status"] == "REJECTED"
    assert payload["status_class"] == AlgoStatusClass.TERMINAL_FAILED.value
    assert diagnostics[0].correlation_id == TEST_ONLY_SESSION_ID
    # The diagnostic decides nothing: the route and the divergence are those of the status.
    assert [r.status_class for r in h.sinks.algo_routes] == [AlgoStatusClass.TERMINAL_FAILED]
    assert h.divergence_kinds() == [StreamDivergenceKind.STREAM_ALGO_TERMINAL_FAILED]


def test_diagnostic_id_is_deterministic_per_session_algo_status_and_reason() -> None:
    frame = algo_update_frame(X="EXPIRED", rm="Synthetic expiry reason")
    ids: list[str] = []
    for session in (TEST_ONLY_SESSION_ID, TEST_ONLY_SESSION_ID, "test-only-other-session"):
        h = Harness(session_id=session)
        h.route_frame(frame)
        (diagnostic,) = h.journal.by_type(ALGO_STATUS_DIAGNOSTIC)
        ids.append(diagnostic.journal_event_id)
    assert ids[0] == ids[1]
    assert ids[0] != ids[2]
    other_reason = Harness()
    other_reason.route_frame(algo_update_frame(X="EXPIRED", rm="Another synthetic reason"))
    (diagnostic,) = other_reason.journal.by_type(ALGO_STATUS_DIAGNOSTIC)
    assert diagnostic.journal_event_id != ids[0]


def test_no_diagnostic_without_a_reject_reason() -> None:
    h = Harness()
    h.route_frame(algo_update_frame(X="EXPIRED"))
    assert h.journal.by_type(ALGO_STATUS_DIAGNOSTIC) == []


# --------------------------------------------------------------------------- #
# ALGO_UPDATE lifecycle de-duplication (change log 2026-08-21, not verified live).
# --------------------------------------------------------------------------- #


def trailing_stop(*, activated: bool, later: bool = False, **overrides: Any) -> dict[str, Any]:
    """A trailing-stop ALGO_UPDATE; `later` moves the event and transaction times forward."""
    shift = 7 if later else 0
    return algo_update_frame(
        event_overrides={
            "E": SYNTHETIC_EVENT_TIME_MS + shift,
            "T": SYNTHETIC_TRANSACTION_TIME_MS + shift,
        },
        **{"o": "TRAILING_STOP_MARKET", "ia": activated, **overrides},
    )


@pytest.mark.parametrize("first_activated", [False, True])
def test_trailing_stop_algo_update_pair_is_one_lifecycle_update(first_activated: bool) -> None:
    h = Harness()
    h.route_frame(trailing_stop(activated=first_activated))
    second = h.route_frame(trailing_stop(activated=not first_activated, later=True))

    assert len(h.sinks.algo_routes) == 1
    assert h.sinks.algo_routes[0].event.is_activated is first_activated
    assert h.total("duplicate_algo_updates") == 1
    assert second.duplicate_algo_updates == 1
    assert second.handled is True
    assert second.algo_routes == 0


def test_trailing_stop_terminal_failed_pair_emits_one_divergence() -> None:
    h = Harness()
    h.route_frame(trailing_stop(activated=False, X="EXPIRED", rm="Synthetic expiry reason"))
    h.route_frame(
        trailing_stop(activated=True, later=True, X="EXPIRED", rm="Synthetic expiry reason")
    )

    assert h.divergence_kinds() == [StreamDivergenceKind.STREAM_ALGO_TERMINAL_FAILED]
    assert len(h.journal.by_type(ALGO_STATUS_DIAGNOSTIC)) == 1
    assert len(h.sinks.algo_routes) == 1
    assert h.total("duplicate_algo_updates") == 1


def test_unknown_algo_pair_journals_one_anomaly() -> None:
    h = Harness(algos=())
    h.route_frame(trailing_stop(activated=False))
    h.route_frame(trailing_stop(activated=True, later=True))

    assert len(h.anomaly_records()) == 1
    assert len(h.journal.calls) == 1
    assert h.divergence_kinds() == [StreamDivergenceKind.UNKNOWN_STREAM_ALGO]
    assert h.total("duplicate_algo_updates") == 1


def test_algo_status_change_is_not_deduplicated() -> None:
    h = Harness()
    h.route_frame(algo_update_frame(X="NEW"))
    h.route_frame(algo_update_frame(X="CANCELED"))

    assert [r.event.algo_status for r in h.sinks.algo_routes] == ["NEW", "CANCELED"]
    assert h.total("duplicate_algo_updates") == 0


def test_exact_duplicate_algo_frame_is_idempotent() -> None:
    h = Harness()
    frame = algo_update_frame(X="REJECTED", rm="Synthetic reject reason")
    h.route_frame(frame)
    h.route_frame(frame, received_offset_s=3)

    assert len(h.sinks.algo_routes) == 1
    assert h.divergence_kinds() == [StreamDivergenceKind.STREAM_ALGO_TERMINAL_FAILED]
    assert len(h.journal.by_type(ALGO_STATUS_DIAGNOSTIC)) == 1
    assert h.total("duplicate_algo_updates") == 1


def test_a_trigger_with_an_actual_order_id_is_a_new_lifecycle_update() -> None:
    h = Harness()
    h.route_frame(algo_update_frame(X="TRIGGERED"))
    h.route_frame(algo_update_frame(X="TRIGGERED", ai="8000000777", aq="0.010"))
    assert len(h.sinks.algo_routes) == 2
    assert h.total("duplicate_algo_updates") == 0


def test_algo_lifecycle_memory_is_per_router_instance() -> None:
    frame = algo_update_frame()
    first = Harness()
    first.route_frame(frame)
    second = Harness()
    second.route_frame(frame)
    assert len(first.sinks.algo_routes) == 1
    assert len(second.sinks.algo_routes) == 1


# --------------------------------------------------------------------------- #
# Account events, listenKeyExpired, ignored events.
# --------------------------------------------------------------------------- #


def test_account_update_reaches_the_account_sink_unchanged_and_nothing_else() -> None:
    h = Harness()
    outcome = parse_stream_message(account_update_frame(), observed_at_utc=T0)
    assert isinstance(outcome, AccountUpdateEvent)
    result = h.router.route(
        TrustedEvent(outcome=outcome, received_at_utc=T0, connection_epoch=1, after_gap=False)
    )

    assert result.account_events == 1
    assert h.sinks.account_events == [outcome]
    assert h.sinks.account_events[0] is outcome
    assert h.sinks.fills == h.sinks.status_hints == h.sinks.algo_routes == []
    assert h.sinks.divergences == []
    assert h.journal.events == {}


def test_account_config_update_is_journaled_as_a_hint() -> None:
    h = Harness()
    result = h.route_frame(account_config_update_frame())

    (record,) = h.journal.by_type(ACCOUNT_CONFIG_HINT)
    payload = json.loads(record.payload_json)
    assert payload["symbol"] == "BTCUSDT"
    assert payload["leverage"] == "5"
    assert payload["multi_assets"] is None
    assert record.correlation_id == TEST_ONLY_SESSION_ID
    assert result.config_hints == 1
    assert h.sinks.divergences == []

    multi = Harness()
    multi.route_frame(account_config_update_frame(ac=OMIT, ai={"j": True}))
    (record,) = multi.journal.by_type(ACCOUNT_CONFIG_HINT)
    payload = json.loads(record.payload_json)
    assert payload["multi_assets"] == "true"
    assert payload["symbol"] is None


@pytest.mark.parametrize(
    ("frame", "counter"),
    [
        (listen_key_expired_frame(), "listen_key_expired"),
        (trade_lite_frame(), "ignored"),
        (strategy_update_frame(), "ignored"),
        (grid_update_frame(), "ignored"),
    ],
)
def test_listen_key_expired_and_ignored_events_only_count(
    frame: dict[str, Any], counter: str
) -> None:
    h = Harness()
    result = h.route_frame(frame)
    assert result.handled is True
    assert getattr(result, counter) == 1
    for name in ("fills", "status_hints", "exchange_states", "algo_routes", "account_events"):
        assert getattr(h.sinks, name) == []
    assert h.sinks.divergences == []
    assert h.journal.calls == []


# --------------------------------------------------------------------------- #
# Stream anomalies: journaled, surfaced, never coerced.
# --------------------------------------------------------------------------- #

ANOMALY_FRAMES: list[tuple[str, dict[str, Any], StreamAnomalyKind]] = [
    ("malformed", trade(T=OMIT), StreamAnomalyKind.MALFORMED_PAYLOAD),
    ("unknown-status", trade(X="SYNTHETIC_UNSEEN"), StreamAnomalyKind.UNKNOWN_ORDER_STATUS),
    (
        "unknown-execution",
        trade(x="SYNTHETIC_UNSEEN"),
        StreamAnomalyKind.UNKNOWN_EXECUTION_TYPE,
    ),
    ("forced-close", trade(c="autoclose-synthetic-0001"), StreamAnomalyKind.FORCED_CLOSE_ORDER),
    ("amendment", trade(x="AMENDMENT"), StreamAnomalyKind.AMENDMENT_EVENT),
    ("liquidation", trade(x="CALCULATED"), StreamAnomalyKind.LIQUIDATION_EVENT),
    (
        "unknown-algo-status",
        algo_update_frame(X="SYNTHETIC_UNSEEN"),
        StreamAnomalyKind.UNKNOWN_ALGO_STATUS,
    ),
    ("margin-call", margin_call_frame(), StreamAnomalyKind.UNHANDLED_EVENT),
    ("deprecated", conditional_order_trigger_reject_frame(), StreamAnomalyKind.DEPRECATED_EVENT),
    (
        "unknown-event",
        {"e": "SYNTHETIC_UNSEEN_EVENT", "E": 1},
        StreamAnomalyKind.UNKNOWN_EVENT_TYPE,
    ),
    ("unrecognized", {"no": "event"}, StreamAnomalyKind.UNRECOGNIZED_ENVELOPE),
]


@pytest.mark.parametrize(
    ("label", "frame", "kind"), ANOMALY_FRAMES, ids=[row[0] for row in ANOMALY_FRAMES]
)
@pytest.mark.parametrize("after_gap", [False, True])
def test_every_anomaly_is_journaled_and_surfaced(
    label: str, frame: dict[str, Any], kind: StreamAnomalyKind, after_gap: bool
) -> None:
    h = Harness()
    result = h.route_frame(frame, after_gap=after_gap)

    assert result.handled is True
    assert result.anomalies == 1
    (record,) = h.anomaly_records()
    payload = json.loads(record.payload_json)
    assert payload["kind"] == kind.value
    assert record.correlation_id == TEST_ONLY_SESSION_ID
    (divergence,) = h.sinks.divergences
    assert divergence.kind is StreamDivergenceKind.STREAM_ANOMALY
    assert divergence.anomaly_kind == kind.value
    assert divergence.payload_sha256 == payload["payload_sha256"]
    assert divergence.after_gap is after_gap
    assert h.sinks.fills == h.sinks.status_hints == h.sinks.algo_routes == []
    assert h.sinks.exchange_states == []
    assert h.sinks.account_events == []


def test_the_same_anomaly_twice_in_a_session_is_one_journal_record() -> None:
    h = Harness()
    frame = trade(X="SYNTHETIC_UNSEEN")
    h.route_frame(frame)
    # Received later: the observation time differs, the payload hash and the id do not.
    h.route_frame(frame, received_offset_s=9)

    assert len(h.anomaly_records()) == 1
    assert len(h.journal.calls) == 1
    assert len(h.sinks.divergences) == 2

    other_session = Harness(session_id="test-only-other-session")
    other_session.route_frame(frame)
    assert (
        other_session.anomaly_records()[0].journal_event_id
        != h.anomaly_records()[0].journal_event_id
    )


def test_an_unexpected_outcome_object_never_raises_and_is_journaled() -> None:
    h = Harness()
    result = h.router.route(
        TrustedEvent(
            outcome=object(),  # type: ignore[arg-type]
            received_at_utc=T0,
            connection_epoch=1,
            after_gap=False,
        )
    )
    assert result.handled is False
    assert len(h.anomaly_records(StreamAnomalyKind.UNRECOGNIZED_ENVELOPE.value)) == 1
    assert h.divergence_kinds() == [StreamDivergenceKind.STREAM_ANOMALY]


# --------------------------------------------------------------------------- #
# Failing sinks and a failing journal.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("failing", ["fill_sink", "exchange_state_sink", "status_hint_sink"])
def test_a_failing_sink_does_not_stop_routing(failing: str) -> None:
    h = Harness()
    h.sinks.failing.add(failing)
    result = h.route_frame(trade(**A))

    assert result.sink_failures == 1
    (record,) = h.anomaly_records(ROUTER_SINK_FAILURE)
    payload = json.loads(record.payload_json)
    assert payload["field"] == failing
    assert "InjectedSinkFailure" in payload["detail"]
    assert "TEST_ONLY failure" not in record.payload_json  # the type only, never the message
    others = {
        "fill_sink": h.sinks.fills,
        "exchange_state_sink": h.sinks.exchange_states,
        "status_hint_sink": h.sinks.status_hints,
    }
    for name, recorded in others.items():
        assert len(recorded) == (0 if name == failing else 1)


@pytest.mark.parametrize(
    ("failing", "frame", "orders", "algos"),
    [
        ("divergence_sink", trade(X="SYNTHETIC_UNSEEN"), (ENTRY,), (STOP,)),
        ("algo_sink", algo_update_frame(X="REJECTED"), (ENTRY,), (STOP,)),
        ("account_sink", account_update_frame(), (ENTRY,), (STOP,)),
        ("fills_fallback", trade(**C), (ENTRY,), (STOP,)),
    ],
)
def test_other_failing_sinks_are_recorded_and_isolated(
    failing: str,
    frame: dict[str, Any],
    orders: tuple[KnownOrder, ...],
    algos: tuple[KnownOrder, ...],
) -> None:
    h = Harness(orders=orders, algos=algos)
    h.sinks.failing.add(failing)
    result = h.route_frame(frame)
    assert result.sink_failures == 1
    assert [
        json.loads(r.payload_json)["field"] for r in h.anomaly_records(ROUTER_SINK_FAILURE)
    ] == [failing]
    if failing == "divergence_sink":
        assert h.divergence_kinds() == []  # the failing sink is the only way to surface one
    elif failing == "algo_sink":
        # The loss is surfaced, and the terminal-failed divergence still reaches its sink.
        assert h.divergence_kinds() == [
            StreamDivergenceKind.SINK_FAILURE,
            StreamDivergenceKind.STREAM_ALGO_TERMINAL_FAILED,
        ]
    elif failing == "fills_fallback":
        assert h.divergence_kinds() == [
            StreamDivergenceKind.STREAM_FILL_TOTAL_MISMATCH,
            StreamDivergenceKind.SINK_FAILURE,
        ]
    else:
        assert h.divergence_kinds() == [StreamDivergenceKind.SINK_FAILURE]


@pytest.mark.parametrize("failing", ["fill_sink", "exchange_state_sink", "status_hint_sink"])
def test_a_failing_order_sink_surfaces_a_sink_failure_divergence_with_the_order_identity(
    failing: str,
) -> None:
    """Review WR-04: a lost fill or status must reach the reconciler, not only the journal."""
    h = Harness()
    h.sinks.failing.add(failing)
    h.route_frame(trade(**A), after_gap=True)

    (divergence,) = h.sinks.divergences
    assert divergence.kind is StreamDivergenceKind.SINK_FAILURE
    assert divergence.client_order_id == ENTRY.client_id
    assert divergence.anomaly_kind == ROUTER_SINK_FAILURE
    assert divergence.after_gap is True
    assert divergence.payload_sha256 is not None
    assert "TEST_ONLY failure" not in divergence.reason  # the sink name only, no message


def test_an_algo_update_lost_by_a_failing_sink_is_routed_again_on_redelivery() -> None:
    h = Harness()
    frame = algo_update_frame(X="NEW")
    h.sinks.failing.add("algo_sink")
    first = h.route_frame(frame)
    assert first.sink_failures == 1
    assert h.sinks.algo_routes == []
    assert h.divergence_kinds() == [StreamDivergenceKind.SINK_FAILURE]
    assert h.divergence_kinds()[0].value == "SINK_FAILURE"
    assert h.sinks.divergences[0].client_algo_id == STOP.client_id

    h.sinks.failing.discard("algo_sink")
    second = h.route_frame(frame)
    assert second.duplicate_algo_updates == 0
    assert len(h.sinks.algo_routes) == 1

    third = h.route_frame(frame)  # now a real duplicate
    assert third.duplicate_algo_updates == 1
    assert len(h.sinks.algo_routes) == 1


def test_every_sink_name_is_a_router_keyword() -> None:
    import inspect

    parameters = inspect.signature(UserDataRouter.__init__).parameters
    assert set(SINK_NAMES) <= set(parameters)
    assert all(
        parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        and parameters[name].default is inspect.Parameter.empty
        for name in parameters
        if name != "self"
    )


def test_a_failing_journal_is_re_raised_and_nothing_is_lost() -> None:
    journal = RecordingJournal(fail=True)
    h = Harness(journal=journal)
    frame = trade(X="SYNTHETIC_UNSEEN")
    with pytest.raises(InjectedJournalFailure):
        h.route_frame(frame)
    # A failing sink cannot be recorded either: the journal failure propagates.
    h.sinks.failing.add("fill_sink")
    with pytest.raises(InjectedJournalFailure):
        h.route_frame(trade(**A))

    # The journal recovers: the same frame is journaled on redelivery (not remembered as done).
    journal.fail = False
    h.route_frame(frame)
    assert len(h.anomaly_records(StreamAnomalyKind.UNKNOWN_ORDER_STATUS.value)) == 1


def test_a_failing_journal_on_an_algo_update_leaves_the_lifecycle_key_unseen() -> None:
    journal = RecordingJournal(fail=True)
    h = Harness(journal=journal, algos=())
    frame = algo_update_frame()
    with pytest.raises(InjectedJournalFailure):
        h.route_frame(frame)
    journal.fail = False
    result = h.route_frame(frame)
    assert result.duplicate_algo_updates == 0
    assert len(h.anomaly_records()) == 1


# --------------------------------------------------------------------------- #
# No listenKey in any output.
# --------------------------------------------------------------------------- #


def test_no_router_output_contains_a_listen_key_from_an_input_frame() -> None:
    h = Harness()
    frames = [
        listen_key_expired_frame(),
        listen_key_expired_frame(E=OMIT),
        listen_key_expired_frame(E="not-an-int"),
        listen_key_expired_frame(e="SYNTHETIC_UNSEEN_EVENT"),
    ]
    for frame in frames:
        assert SYNTHETIC_LISTEN_KEY in json.dumps(frame)
        h.route_frame(frame, after_gap=True)

    outputs: list[str] = [repr(result) for result in h.results]
    outputs += [repr(event) for event in h.journal.calls]
    outputs += [event.payload_json for event in h.journal.calls]
    for name in (
        "fills",
        "status_hints",
        "exchange_states",
        "algo_routes",
        "account_events",
        "divergences",
    ):
        outputs += [repr(entry) for entry in getattr(h.sinks, name)]
    assert len(h.anomaly_records()) == 3
    assert all(SYNTHETIC_LISTEN_KEY not in text for text in outputs)


# --------------------------------------------------------------------------- #
# Construction and module surface.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("session_id", ["", "x" * 129])
def test_router_refuses_an_unusable_session_id(session_id: str) -> None:
    with pytest.raises(ValueError):
        Harness(session_id=session_id)


def test_module_exports() -> None:
    assert {
        "KnownOrder",
        "OrderLookup",
        "StreamDivergence",
        "FillTotalsTracker",
        "RouteResult",
        "UserDataRouter",
    } <= set(router_mod.__all__)
