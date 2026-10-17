"""The RECORDED_DEMO frames go through the real parsers, the replay proof and the router.

Phase 18, plan 18-21 Task 1 (D-17, D-21). The frames under `tests/fixtures/phase18/recorded_demo/`
were captured on the Binance DEMO environment (not mainnet) by the user-run smoke
(`smoke/`, 2026-10-16T14:04:46Z) and by the second user-run probe (`probe/`,
2026-10-16T17:36:12Z). They are evidence and are never edited. The synthetic frames of
`tests/fixtures/phase18/synthetic/` (SYNTHETIC_FROM_SDK_MODEL) stay and complement them.

What this file pins, from the real frames:

* every recorded file is listed in its `provenance.md` with the label RECORDED_DEMO, and in the
  README of the fixtures directory;
* every frame parses to a typed event, or to an IgnoredEvent (TRADE_LITE, ignored by design),
  or to a StreamAnomaly named in `KNOWN_RECORDED_ANOMALIES` (empty: the evidence has none);
* every wire key the real frames carry is either read by the parser or named in
  `IGNORED_WIRE_FIELDS` with a reason, so a new Binance field is visible;
* the real field types (integer ids, empty `ai`, string decimals) become the parsed values;
* the recorded fills fold to one position view in every delivery order, with duplicates;
* the router fed the recorded frames emits the expected fills, algo routes and no anomaly.

No network, no clock (the router's clock is a constant), no randomness.
"""

from __future__ import annotations

import itertools
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_userdata_events import (
    ACCOUNT_BALANCE_WIRE_FIELDS,
    ACCOUNT_POSITION_WIRE_FIELDS,
    ACCOUNT_UPDATE_WIRE_FIELDS,
    ALGO_UPDATE_WIRE_FIELDS,
    ORDER_UPDATE_WIRE_FIELDS,
    AccountUpdateEvent,
    AlgoUpdateEvent,
    IgnoredEvent,
    OrderUpdateEvent,
    StreamAnomaly,
    parse_stream_message,
    to_fill_event,
)
from src.adapters.binance_userdata_router import FillSource, KnownOrder, StreamDivergenceKind
from src.adapters.binance_userdata_supervisor import TrustedEvent
from src.domain.algo_status import AlgoStatusClass
from src.domain.enums import OrderRole, OrderStatus
from src.execution.fill_monitor import (
    CurrentPositionView,
    FoldedPositionView,
    fold_fills,
)

from tests.support.stream_sinks import (
    FakeOrderLookup,
    RecordingJournal,
    RecordingSinks,
    make_router,
)
from tests.support.virtual_time import TEST_ONLY_VIRTUAL_START

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "phase18"
RECORDED_ROOT = FIXTURE_ROOT / "recorded_demo"
README = FIXTURE_ROOT / "README.md"
RECORDED_LABEL = "RECORDED_DEMO"
T0 = TEST_ONLY_VIRTUAL_START

# Frame file name -> expected StreamAnomalyKind value, with the evidence line that explains it.
# Empty: every recorded frame is a typed event or an ignored TRADE_LITE (18-probe-check.txt
# and 18-smoke-check.txt report no anomaly). An entry is added only with its explanation.
KNOWN_RECORDED_ANOMALIES: dict[str, str] = {}

# Wire keys the real frames carry that the parsers do not read, with the reason. A key that is in
# neither the parser's read set nor here fails `test_every_recorded_wire_key_is_read_or_named`.
IGNORED_WIRE_FIELDS: dict[str, dict[str, str]] = {
    "ORDER_TRADE_UPDATE.o": {
        "a": "bids notional of the order (sent by Binance, not part of the project's order model)",
        "b": "asks notional of the order (sent by Binance, not part of the project's order model)",
        "si": "self-trade-prevention id; the project sets no STP group (value 0 in every frame)",
        "ss": "self-trade-prevention mode code; the project sets no STP group (value 0)",
    },
    "ACCOUNT_UPDATE.a.P": {
        "ma": (
            "margin asset of the position (USDT in every frame); the project reads the "
            "position by symbol and does not use the margin asset"
        ),
    },
}

# Event name on the wire -> the outcome class the parser must return for a real frame.
EXPECTED_OUTCOME: dict[str, type] = {
    "ORDER_TRADE_UPDATE": OrderUpdateEvent,
    "ALGO_UPDATE": AlgoUpdateEvent,
    "ACCOUNT_UPDATE": AccountUpdateEvent,
    # TRADE_LITE is ignored by design (fills come from ORDER_TRADE_UPDATE only; 18-DEC-D01).
    "TRADE_LITE": IgnoredEvent,
}

_PROVENANCE_ROW = re.compile(r"^- `(?P<name>[^`]+\.json)`: (?P<label>[A-Z_]+)$")


def _frame_files() -> list[Path]:
    return sorted(RECORDED_ROOT.rglob("*.json"))


def _load(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


FRAMES: dict[str, dict[str, Any]] = {path.name: _load(path) for path in _frame_files()}


def _parse(name: str) -> Any:
    return parse_stream_message(FRAMES[name], observed_at_utc=T0)


# --------------------------------------------------------------------------- #
# Provenance: nothing unlisted, nothing mislabelled.
# --------------------------------------------------------------------------- #


def _provenance_rows(directory: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in (directory / "provenance.md").read_text(encoding="utf-8").splitlines():
        match = _PROVENANCE_ROW.match(line)
        if match is not None:
            assert match["name"] not in rows, f"duplicate provenance row {match['name']}"
            rows[match["name"]] = match["label"]
    return rows


def test_there_are_recorded_frames_from_the_smoke_and_the_probe() -> None:
    assert {p.parent.name for p in _frame_files()} == {"smoke", "probe"}
    assert len(FRAMES) == len(_frame_files()), "two recorded files share one name"
    assert len(FRAMES) >= 58


def test_every_recorded_frame_is_listed_in_its_provenance_file_as_recorded_demo() -> None:
    for directory in (RECORDED_ROOT / "smoke", RECORDED_ROOT / "probe"):
        rows = _provenance_rows(directory)
        files = {p.name for p in directory.glob("*.json")}
        assert files == set(rows), "a recorded file without a provenance row, or the reverse"
        assert set(rows.values()) == {RECORDED_LABEL}


def test_the_fixtures_readme_lists_every_recorded_frame_with_its_label() -> None:
    text = README.read_text(encoding="ascii")
    lines = text.splitlines()
    start = lines.index("## Recorded demo frames") + 1
    section: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        section.append(line)
    body = " ".join(section)
    assert "Demo" in body and "not mainnet" in body
    assert "2026-10-16T14:04:46Z" in body and "2026-10-16T17:36:12Z" in body
    rows: dict[str, str] = {}
    for line in section:
        if not line.startswith("|"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if cells[0] in ("File", "") or set(cells[0]) <= {"-", ":", " "}:
            continue
        name = cells[0].rsplit("/", 1)[-1]
        assert name not in rows, f"duplicate README row {name}"
        rows[name] = cells[-1]
    assert set(rows) == set(FRAMES)
    assert set(rows.values()) == {RECORDED_LABEL}


# --------------------------------------------------------------------------- #
# Every real frame is a typed event, an ignored TRADE_LITE, or an explained anomaly.
# --------------------------------------------------------------------------- #


def test_every_recorded_frame_parses_to_the_expected_outcome() -> None:
    kinds: set[str] = set()
    for name, frame in FRAMES.items():
        outcome = _parse(name)
        if isinstance(outcome, StreamAnomaly):
            assert KNOWN_RECORDED_ANOMALIES.get(name) == outcome.kind.value, (
                f"{name}: unexplained anomaly {outcome.kind.value} {outcome.field}"
            )
            continue
        wire_name = frame["e"]
        kinds.add(wire_name)
        assert isinstance(outcome, EXPECTED_OUTCOME[wire_name]), f"{name}: {type(outcome)}"
    assert kinds == set(EXPECTED_OUTCOME), "the evidence holds all four observed frame kinds"
    assert set(KNOWN_RECORDED_ANOMALIES) <= set(FRAMES)


def test_trade_lite_is_ignored_by_design_and_every_one_matches_its_order_trade_update() -> None:
    """TRADE_LITE adds no fill the ORDER_TRADE_UPDATE does not carry (single fill source)."""
    trades: dict[str, OrderUpdateEvent] = {}
    for name in FRAMES:
        outcome = _parse(name)
        if isinstance(outcome, OrderUpdateEvent) and outcome.trade_id is not None:
            trades[outcome.trade_id] = outcome
    lite_names = [n for n, f in FRAMES.items() if f["e"] == "TRADE_LITE"]
    assert len(lite_names) == 8
    for name in lite_names:
        outcome = _parse(name)
        assert isinstance(outcome, IgnoredEvent)
        assert outcome.event_name == "TRADE_LITE"
        lite = FRAMES[name]
        update = trades[str(lite["t"])]  # the same trade id in the ORDER_TRADE_UPDATE key space
        assert update.client_order_id == lite["c"]
        assert update.exchange_order_id == str(lite["i"])
        assert update.last_filled_quantity == Decimal(lite["l"])
        assert update.last_filled_price == Decimal(lite["L"])
        assert update.side == lite["S"]


# --------------------------------------------------------------------------- #
# The real field set: a new Binance field is visible.
# --------------------------------------------------------------------------- #


def _wire_keys() -> dict[str, set[str]]:
    keys: dict[str, set[str]] = defaultdict(set)
    for frame in FRAMES.values():
        event = frame["e"]
        if event == "ORDER_TRADE_UPDATE":
            keys["ORDER_TRADE_UPDATE"] |= set(frame)
            keys["ORDER_TRADE_UPDATE.o"] |= set(frame["o"])
        elif event == "ALGO_UPDATE":
            keys["ALGO_UPDATE"] |= set(frame)
            keys["ALGO_UPDATE.o"] |= set(frame["o"])
        elif event == "ACCOUNT_UPDATE":
            keys["ACCOUNT_UPDATE"] |= set(frame)
            keys["ACCOUNT_UPDATE.a"] |= set(frame["a"])
            for row in frame["a"]["B"]:
                keys["ACCOUNT_UPDATE.a.B"] |= set(row)
            for row in frame["a"]["P"]:
                keys["ACCOUNT_UPDATE.a.P"] |= set(row)
    return keys


PARSER_READS: dict[str, frozenset[str]] = {
    "ORDER_TRADE_UPDATE": frozenset({"E", "T", "e", "o"}),
    "ORDER_TRADE_UPDATE.o": ORDER_UPDATE_WIRE_FIELDS,
    "ALGO_UPDATE": frozenset({"E", "T", "e", "o"}),
    "ALGO_UPDATE.o": ALGO_UPDATE_WIRE_FIELDS,
    "ACCOUNT_UPDATE": frozenset({"E", "T", "e", "a"}),
    "ACCOUNT_UPDATE.a": ACCOUNT_UPDATE_WIRE_FIELDS,
    "ACCOUNT_UPDATE.a.B": ACCOUNT_BALANCE_WIRE_FIELDS,
    "ACCOUNT_UPDATE.a.P": ACCOUNT_POSITION_WIRE_FIELDS,
}


def test_every_recorded_wire_key_is_read_or_named() -> None:
    observed = _wire_keys()
    assert set(observed) == set(PARSER_READS)
    for place, keys in observed.items():
        ignored = set(IGNORED_WIRE_FIELDS.get(place, {}))
        unexplained = keys - PARSER_READS[place] - ignored
        assert unexplained == set(), f"{place}: new wire keys {sorted(unexplained)}"


def test_every_ignored_wire_field_is_really_observed_and_has_a_reason() -> None:
    observed = _wire_keys()
    for place, fields in IGNORED_WIRE_FIELDS.items():
        for key, reason in fields.items():
            assert key in observed[place], f"{place}.{key} is listed but never observed"
            assert key not in PARSER_READS[place], f"{place}.{key} is read by the parser"
            assert reason.strip()


# --------------------------------------------------------------------------- #
# Real types and shapes the synthetic frames could hide (regression tests).
# --------------------------------------------------------------------------- #

ENTRY_FILL = "full_fill_protective_quantity-005-ORDER_TRADE_UPDATE.json"
EXIT_FILL = "full_fill_protective_quantity-010-ORDER_TRADE_UPDATE.json"
STOP_NEW = "full_fill_protective_quantity-001-ALGO_UPDATE.json"
STOP_CANCELED = "full_fill_protective_quantity-006-ALGO_UPDATE.json"
ACCOUNT = "full_fill_protective_quantity-004-ACCOUNT_UPDATE.json"


def test_real_integer_ids_become_the_string_ids_of_the_domain() -> None:
    frame = FRAMES[ENTRY_FILL]["o"]
    assert isinstance(frame["i"], int) and isinstance(frame["t"], int)  # the wire sends numbers
    event = _parse(ENTRY_FILL)
    assert isinstance(event, OrderUpdateEvent)
    assert event.exchange_order_id == "28636771666"
    assert event.trade_id == "547825183"
    assert event.execution_type == "TRADE" and event.order_status == "FILLED"
    assert event.last_filled_quantity == Decimal("0.0008")
    assert event.last_filled_price == Decimal("81424.2")
    assert event.commission == Decimal("0.02605574") and event.commission_asset == "USDT"
    assert event.is_maker is False and event.reduce_only is False


def test_a_new_order_frame_has_trade_id_zero_and_no_fill() -> None:
    new = "full_fill_protective_quantity-003-ORDER_TRADE_UPDATE.json"
    assert FRAMES[new]["o"]["t"] == 0
    event = _parse(new)
    assert isinstance(event, OrderUpdateEvent)
    assert event.execution_type == "NEW"
    assert to_fill_event(event) is None


def test_real_algo_update_has_an_integer_algo_id_and_an_empty_ai() -> None:
    frame = FRAMES[STOP_NEW]["o"]
    assert isinstance(frame["aid"], int)
    assert frame["ai"] == ""  # no child order yet: the wire sends an empty string, not null
    event = _parse(STOP_NEW)
    assert isinstance(event, AlgoUpdateEvent)
    assert event.algo_id == "1000000243283526"
    assert event.client_algo_id == "dprobe-ffl-20261016T173612Z-14"
    assert event.algo_status == "NEW"
    assert event.actual_order_id is None
    assert event.reject_reason is None
    assert event.reduce_only is True and event.is_activated is False
    assert event.trigger_price == Decimal("78080.1")
    canceled = _parse(STOP_CANCELED)
    assert isinstance(canceled, AlgoUpdateEvent) and canceled.algo_status == "CANCELED"


def test_real_account_update_position_row_with_the_margin_asset_key() -> None:
    event = _parse(ACCOUNT)
    assert isinstance(event, AccountUpdateEvent)
    assert event.reason == "ORDER"
    (balance,) = event.balances
    assert balance.asset == "USDT" and balance.wallet_balance == Decimal("4999.66732864")
    (position,) = event.positions
    assert position.symbol == "BTCUSDT"
    assert position.position_amount == Decimal("0.0008")
    assert position.entry_price == Decimal("81424.2")
    assert position.position_side == "BOTH" and position.margin_type == "cross"


def test_the_smoke_frames_are_the_new_and_canceled_updates_of_the_run() -> None:
    first = _parse("execute-001-ORDER_TRADE_UPDATE.json")
    second = _parse("execute-002-ORDER_TRADE_UPDATE.json")
    assert isinstance(first, OrderUpdateEvent) and isinstance(second, OrderUpdateEvent)
    assert (first.execution_type, second.execution_type) == ("NEW", "CANCELED")
    assert first.client_order_id == second.client_order_id
    assert first.exchange_order_id == second.exchange_order_id == "28636495127"


# --------------------------------------------------------------------------- #
# Replay: the recorded fills fold to one view in every delivery order.
# --------------------------------------------------------------------------- #

FLAT = CurrentPositionView(symbol="BTCUSDT", position_side="BOTH", position_amt=Decimal("0"))
ENTRY_ID = "dprobe-ffe-20261016T173612Z-15"
EXIT_ID = "dprobe-flat-20261016T173612Z-16"
STOP_ID = "dprobe-ffl-20261016T173612Z-14"
SCENARIO = [
    "full_fill_protective_quantity-003-ORDER_TRADE_UPDATE.json",
    ENTRY_FILL,
    "full_fill_protective_quantity-008-ORDER_TRADE_UPDATE.json",
    EXIT_FILL,
]


def _scenario_lookup() -> FakeOrderLookup:
    return FakeOrderLookup.of(
        orders=[
            KnownOrder(
                local_order_id="test-only-local-entry",
                client_id=ENTRY_ID,
                symbol="BTCUSDT",
                role=OrderRole.ENTRY,
                local_status=OrderStatus.NEW,
            ),
            KnownOrder(
                local_order_id="test-only-local-exit",
                client_id=EXIT_ID,
                symbol="BTCUSDT",
                role=OrderRole.STOP_LOSS,
                local_status=OrderStatus.NEW,
            ),
        ],
        algos=[
            KnownOrder(
                local_order_id="test-only-local-stop",
                client_id=STOP_ID,
                symbol="BTCUSDT",
                role=OrderRole.STOP_LOSS,
                local_status=OrderStatus.NEW,
            )
        ],
    )


@dataclass
class Run:
    view: FoldedPositionView
    sinks: RecordingSinks
    journal: RecordingJournal


def _run(sequence: list[str], lookup: FakeOrderLookup | None = None) -> Run:
    sinks = RecordingSinks()
    journal = RecordingJournal()
    router = make_router(
        lookup=lookup if lookup is not None else _scenario_lookup(),
        journal=journal,
        sinks=sinks,
        clock=lambda: T0,
    )
    for index, name in enumerate(sequence):
        received = T0 + timedelta(milliseconds=index)
        outcome = parse_stream_message(FRAMES[name], observed_at_utc=received)
        router.route(
            TrustedEvent(
                outcome=outcome, received_at_utc=received, connection_epoch=1, after_gap=False
            )
        )
    view = fold_fills(fill_events=sinks.fill_events(), current_position_view=FLAT)
    return Run(view=view, sinks=sinks, journal=journal)


BASELINE = _run(SCENARIO)


def test_baseline_of_the_recorded_scenario_is_one_buy_and_one_sell_fill() -> None:
    fills = BASELINE.sinks.fill_events()
    assert [(f.exchange_trade_id, f.side, f.fill_quantity) for f in fills] == [
        ("547825183", "BUY", Decimal("0.0008")),
        ("547825188", "SELL", Decimal("0.0008")),
    ]
    assert BASELINE.view.fill_count == 2
    assert BASELINE.sinks.fallback_calls == []
    assert BASELINE.journal.events == {}
    assert BASELINE.sinks.divergences == []


def test_every_ordering_of_the_recorded_frames_with_duplicates_gives_one_view() -> None:
    orderings = sorted(set(itertools.permutations(SCENARIO * 2)))
    assert len(orderings) == 2520
    for ordering in orderings:
        result = _run(list(ordering))
        assert result.view == BASELINE.view
        assert result.view.fill_count == 2
        assert result.sinks.fallback_calls == []
        assert result.journal.events == {}


def test_replaying_the_whole_recorded_sequence_twice_gives_the_same_view() -> None:
    once = _run(SCENARIO)
    twice = _run(SCENARIO + SCENARIO)
    assert twice.view == once.view == BASELINE.view
    assert twice.sinks.fallback_calls == once.sinks.fallback_calls == []


# --------------------------------------------------------------------------- #
# The router over every recorded frame.
# --------------------------------------------------------------------------- #


def _lookup_for_all_frames() -> FakeOrderLookup:
    orders: dict[str, KnownOrder] = {}
    algos: dict[str, KnownOrder] = {}
    for frame in FRAMES.values():
        if frame["e"] == "ORDER_TRADE_UPDATE":
            client_id = frame["o"]["c"]
            orders.setdefault(
                client_id,
                KnownOrder(
                    local_order_id=f"test-only-local-{len(orders)}",
                    client_id=client_id,
                    symbol=frame["o"]["s"],
                    role=OrderRole.STOP_LOSS if frame["o"]["R"] else OrderRole.ENTRY,
                    local_status=OrderStatus.NEW,
                ),
            )
        elif frame["e"] == "ALGO_UPDATE":
            client_id = frame["o"]["caid"]
            algos.setdefault(
                client_id,
                KnownOrder(
                    local_order_id=f"test-only-local-algo-{len(algos)}",
                    client_id=client_id,
                    symbol=frame["o"]["s"],
                    role=OrderRole.STOP_LOSS,
                    local_status=OrderStatus.NEW,
                ),
            )
    return FakeOrderLookup(orders=orders, algos=algos)


def _in_recorded_order() -> list[str]:
    # The probe scenarios in the order of their evidence file names, then the smoke frames.
    return sorted(FRAMES, key=lambda n: (n.startswith("execute-"), n))


def test_router_over_every_recorded_frame_emits_the_expected_fills_and_no_anomaly() -> None:
    result = _run(_in_recorded_order(), _lookup_for_all_frames())

    expected_trades = {
        name
        for name, frame in FRAMES.items()
        if frame["e"] == "ORDER_TRADE_UPDATE" and frame["o"]["x"] == "TRADE"
    }
    assert len(expected_trades) == 8
    fills = result.sinks.fills
    assert len(fills) == len(expected_trades)
    assert {r.source for r in fills} == {FillSource.USER_DATA_EVENT}
    assert len({(f.fill.order_id, f.fill.exchange_trade_id) for f in fills}) == len(fills)
    for routed in fills:
        assert routed.fill.fill_quantity == Decimal("0.0008")
        assert routed.fill.commission is not None and routed.fill.commission_asset == "USDT"

    # No anomaly, no divergence, no REST fallback: the recorded stream is self-consistent.
    assert result.sinks.divergences == []
    assert result.journal.events == {}
    assert result.sinks.fallback_calls == []

    algo_frames = [n for n, f in FRAMES.items() if f["e"] == "ALGO_UPDATE"]
    assert len(algo_frames) == 16
    # Every recorded algo update has its own lifecycle key (algo id and status): all 16 are routed.
    assert len(result.sinks.algo_routes) == len(algo_frames)
    order_frames = [n for n, f in FRAMES.items() if f["e"] == "ORDER_TRADE_UPDATE"]
    assert len(order_frames) == 26
    assert len(result.sinks.status_hints) == len(order_frames)
    # The Demo sent only NEW and CANCELED. CANCELED stays UNKNOWN: that class is the owner's
    # recorded decision (decisions/18-DEC-O-18-01.md), and a Demo observation does not change it.
    by_status = {route.event.algo_status: route.status_class for route in result.sinks.algo_routes}
    assert by_status == {"NEW": AlgoStatusClass.ACTIVE, "CANCELED": AlgoStatusClass.UNKNOWN}

    account_frames = [n for n, f in FRAMES.items() if f["e"] == "ACCOUNT_UPDATE"]
    assert len(result.sinks.account_events) == len(account_frames)


def test_router_surfaces_every_recorded_order_and_algo_as_unknown_without_a_lookup() -> None:
    result = _run(_in_recorded_order(), FakeOrderLookup())
    assert result.sinks.fills == []
    assert result.sinks.algo_routes == []
    kinds = [d.kind for d in result.sinks.divergences]
    assert kinds.count(StreamDivergenceKind.UNKNOWN_STREAM_ORDER) == 26
    assert kinds.count(StreamDivergenceKind.UNKNOWN_STREAM_ALGO) == 16
    assert len(kinds) == 42


@pytest.mark.parametrize("name", ["execute-001-ORDER_TRADE_UPDATE.json"])
def test_recorded_frames_are_not_modified_by_parsing(name: str) -> None:
    before = json.dumps(FRAMES[name], sort_keys=True)
    _parse(name)
    assert json.dumps(FRAMES[name], sort_keys=True) == before
