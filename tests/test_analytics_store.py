"""Edge-adapter tests for the analytics store (Phase 10, plan 10-09, D-01/D-02/D-05).

The reader is SELECT-only; the single write is the guarded, idempotent
KILL_GATE_EVALUATION append; candles come from the immutable 1m Parquet store read-only.
Async wrappers are driven by fake sessions; statement semantics run on sync SQLite (no
aiosqlite dependency); the PG integration test skips without TEST_DATABASE_URL.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import os
import random
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql import Select
from src.adapters import analytics_store
from src.adapters.analytics_store import (
    CandleReadResult,
    JournalReadResult,
    LiveRows,
    append_kill_gate_event,
    build_append_stmt,
    journal_rows_to_events,
    read_candles,
    read_journal_events,
    read_live_rows,
    select_journal_events_stmt,
)
from src.adapters.binance_usdm import Kline
from src.analytics.excursion import compute_trade_excursion
from src.analytics.inputs import normalize_backtest
from src.data.store import publish_batch
from src.db.mappers import journal_to_row, signal_to_row
from src.db.models import Base, JournalEventRow
from src.domain.enums import SignalStatus
from src.domain.journal import JournalEvent, content_hash_event_id
from src.domain.signal import Signal

from tests.phase10_helpers import (
    load_input,
    make_candles,
    make_trade_record,
    parse_utc,
)

KGE = "KILL_GATE_EVALUATION"
T0 = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _event(
    *,
    event_type: str = KGE,
    entity_id: str = "KILL_GATE_D013",
    at: datetime = T0,
    payload: str = '{"state":"WITHIN_BUDGET"}',
) -> JournalEvent:
    return JournalEvent(
        journal_event_id=content_hash_event_id(
            prefix="kill_gate",
            event_type=event_type,
            entity_id=entity_id,
            occurred_at_utc=at,
            payload_json=payload,
        ),
        occurred_at_utc=at,
        event_type=event_type,
        entity_type="KillGate",
        entity_id=entity_id,
        correlation_id="analytics_kill_gate",
        payload_json=payload,
    )


def _signal(signal_id: str) -> Signal:
    return Signal(
        signal_id=signal_id,
        strategy_id="trend-pullback",
        strategy_version="v1.0.0",
        parameter_set_id="baseline-v1",
        parameter_set_hash="b" * 64,
        symbol="BTCUSDT",
        direction="LONG",
        setup_type="pullback",
        source_timeframe="1h",
        source_candle_close_utc=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
        detected_at_utc=datetime(2026, 9, 19, 12, 5, tzinfo=UTC),
        status=SignalStatus.DETECTED,
        expires_at_utc=datetime(2026, 9, 19, 16, 0, tzinfo=UTC),
        invalidated_at_utc=None,
    )


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class _FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeAsyncSession:
    """Queue of row batches; records every executed statement."""

    def __init__(self, batches: list[list[Any]] | None = None) -> None:
        self.batches = list(batches or [])
        self.statements: list[Any] = []
        self.commits = 0

    async def execute(self, statement: Any) -> _FakeResult:
        self.statements.append(statement)
        return _FakeResult(self.batches.pop(0) if self.batches else [])

    async def commit(self) -> None:
        self.commits += 1


class _SyncBackedAsyncSession:
    """Async facade over a real sync SQLite session (statement semantics, no aiosqlite)."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.commits = 0

    def get_bind(self) -> Any:
        return self._session.get_bind()

    async def execute(self, statement: Any) -> Any:
        return self._session.execute(statement)

    async def commit(self) -> None:
        self.commits += 1
        self._session.commit()


@pytest.fixture
def sqlite_session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _row_count(session: Session) -> int:
    return int(session.execute(select(func.count()).select_from(JournalEventRow)).scalar_one())


# --------------------------------------------------------------------------- #
# Journal statement + row conversion
# --------------------------------------------------------------------------- #


def test_select_stmt_orders_by_the_total_key() -> None:
    sql = str(select_journal_events_stmt().compile(dialect=sqlite.dialect()))
    order_clause = sql.split("ORDER BY", 1)[1]
    positions = [
        order_clause.index(column)
        for column in ("occurred_at_utc", "event_type", "entity_id", "journal_event_id")
    ]
    assert positions == sorted(positions)
    assert "WHERE" not in sql


def test_select_stmt_filters_event_types() -> None:
    sql = str(
        select_journal_events_stmt(event_types=[KGE, "ENTRY_EXPIRY"]).compile(
            dialect=sqlite.dialect()
        )
    )
    assert "event_type IN" in sql


def test_select_stmt_semantics_on_sqlite_follow_the_total_key(sqlite_session: Session) -> None:
    events = [
        _event(event_type="B_TYPE", entity_id="e2", at=T0 + timedelta(minutes=1)),
        _event(event_type="A_TYPE", entity_id="e9", at=T0),
        _event(event_type="A_TYPE", entity_id="e1", at=T0),
        _event(event_type="B_TYPE", entity_id="e1", at=T0),
    ]
    random.Random(7).shuffle(events)
    for event in events:
        sqlite_session.add(journal_to_row(event))
    sqlite_session.commit()

    rows = sqlite_session.execute(select_journal_events_stmt()).scalars().all()
    got = [(r.event_type, r.entity_id) for r in rows]
    assert got == [("A_TYPE", "e1"), ("A_TYPE", "e9"), ("B_TYPE", "e1"), ("B_TYPE", "e2")]

    only_b = sqlite_session.execute(select_journal_events_stmt(event_types=["B_TYPE"]))
    assert {r.event_type for r in only_b.scalars().all()} == {"B_TYPE"}


def test_rows_to_events_counts_malformed_rows_and_never_raises() -> None:
    good = journal_to_row(_event(entity_id="ok"))
    bad_json = journal_to_row(_event(entity_id="badjson"))
    bad_json.payload_json = "{not json"
    naive = journal_to_row(_event(entity_id="naive"))
    naive.occurred_at_utc = datetime(2026, 9, 29, 12, 0)
    events, rejected = journal_rows_to_events([bad_json, good, naive])
    assert rejected == 2
    assert [e.entity_id for e in events] == ["ok"]


def test_rows_to_events_orders_by_the_total_key_regardless_of_row_order() -> None:
    events = [
        _event(event_type="B", entity_id="x", at=T0 + timedelta(seconds=5)),
        _event(event_type="A", entity_id="y", at=T0),
        _event(event_type="A", entity_id="x", at=T0),
        _event(event_type="C", entity_id="z", at=T0 - timedelta(hours=1)),
    ]
    rows = [journal_to_row(e) for e in events]
    expected = tuple(
        sorted(
            events,
            key=lambda e: (e.occurred_at_utc, e.event_type, e.entity_id, e.journal_event_id),
        )
    )
    for seed in range(5):
        shuffled = list(rows)
        random.Random(seed).shuffle(shuffled)
        got, rejected = journal_rows_to_events(shuffled)
        assert rejected == 0
        assert got == expected


async def test_read_journal_events_uses_a_select_and_converts_rows() -> None:
    rows = [journal_to_row(_event(entity_id="b")), journal_to_row(_event(entity_id="a"))]
    session = _FakeAsyncSession([rows])
    result = await read_journal_events(session, event_types=[KGE])  # type: ignore[arg-type]
    assert isinstance(result, JournalReadResult)
    assert [e.entity_id for e in result.events] == ["a", "b"]
    assert result.rejected == 0
    assert len(session.statements) == 1
    assert isinstance(session.statements[0], Select)
    assert session.commits == 0


async def test_read_live_rows_issues_six_selects_and_counts_rejects() -> None:
    good = signal_to_row(_signal("s" * 64))
    other = signal_to_row(_signal("a" * 64))
    bad = signal_to_row(_signal("c" * 64))
    bad.status = "BOGUS"
    session = _FakeAsyncSession([[good, bad, other], [], [], [], [], []])
    result = await read_live_rows(session)  # type: ignore[arg-type]
    assert isinstance(result, LiveRows)
    assert [s.signal_id for s in result.signals] == ["a" * 64, "s" * 64]
    assert result.plans == result.approvals == result.orders == ()
    assert result.fills == result.positions == ()
    assert dict(result.rejected) == {
        "signals": 1,
        "trade_plans": 0,
        "approvals": 0,
        "orders": 0,
        "fills": 0,
        "positions": 0,
    }
    assert len(session.statements) == 6
    assert all(isinstance(s, Select) for s in session.statements)
    assert session.commits == 0


# --------------------------------------------------------------------------- #
# Guarded single append
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("dialect", "module"), [("postgresql", postgresql), ("sqlite", sqlite)])
def test_append_stmt_is_on_conflict_do_nothing(dialect: str, module: Any) -> None:
    stmt = build_append_stmt(_event(), dialect)
    sql = str(stmt.compile(dialect=module.dialect()))
    assert sql.startswith("INSERT INTO journal_events")
    assert "ON CONFLICT (journal_event_id) DO NOTHING" in sql


def test_append_stmt_rejects_unsupported_dialects() -> None:
    with pytest.raises(ValueError, match="dialect"):
        build_append_stmt(_event(), "mysql")


def test_append_stmt_duplicate_inserts_exactly_one_row(sqlite_session: Session) -> None:
    event = _event()
    stmt = build_append_stmt(event, "sqlite")
    sqlite_session.execute(stmt)
    sqlite_session.execute(stmt)
    sqlite_session.commit()
    assert _row_count(sqlite_session) == 1


async def test_append_kill_gate_event_refuses_other_event_types_before_any_statement() -> None:
    session = _FakeAsyncSession()
    with pytest.raises(ValueError, match=KGE):
        await append_kill_gate_event(session, _event(event_type="ENTRY_EXPIRY"))  # type: ignore[arg-type]
    assert session.statements == []
    assert session.commits == 0


async def test_append_kill_gate_event_is_idempotent_on_replay(sqlite_session: Session) -> None:
    session = _SyncBackedAsyncSession(sqlite_session)
    event = _event()
    await append_kill_gate_event(session, event)  # type: ignore[arg-type]
    await append_kill_gate_event(session, event)  # type: ignore[arg-type]
    assert session.commits == 2
    assert _row_count(sqlite_session) == 1
    stored = sqlite_session.execute(select(JournalEventRow)).scalars().one()
    assert stored.journal_event_id == event.journal_event_id
    assert stored.event_type == KGE
    assert stored.payload_json == event.payload_json


def _function_names_calling(tree: ast.AST, callee_names: set[str]) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id in callee_names
                ):
                    found.add(node.name)
    return found


def test_module_has_exactly_one_insert_building_function() -> None:
    tree = ast.parse(inspect.getsource(analytics_store))
    assert _function_names_calling(tree, {"pg_insert", "sqlite_insert"}) == {"build_append_stmt"}
    # No update / delete / raw-text / DDL construction anywhere in the module.
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not called & {"update", "delete", "text", "insert"}


def test_read_functions_contain_no_write_constructs() -> None:
    for func_ in (read_journal_events, read_live_rows, select_journal_events_stmt):
        source = inspect.getsource(func_)
        lowered = source.lower()
        for token in ("insert", "update(", "delete(", "text(", "commit", "add(", "flush"):
            assert token not in lowered, f"{func_.__name__} contains {token!r}"


def test_adapter_source_has_no_float_and_no_secret_or_network_use() -> None:
    tree = ast.parse(inspect.getsource(analytics_store))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "float"
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float)
    source = inspect.getsource(analytics_store)
    for token in ("DATABASE_URL", "requests", "httpx", "binance"):
        assert token not in source


# --------------------------------------------------------------------------- #
# Candle reader
# --------------------------------------------------------------------------- #


def _klines_from_candles(candles: list[Any]) -> list[Kline]:
    return [
        Kline(
            symbol=c.symbol,
            interval="1m",
            open_time_utc=c.open_time_utc,
            close_time_utc=c.close_time_utc,
            open=c.open,
            high=c.high,
            low=c.low,
            close=c.close,
            volume=c.volume,
            quote_volume=Decimal("1"),
            trade_count=1,
        )
        for c in candles
    ]


def test_read_candles_round_trips_through_publish_batch(tmp_path: Path) -> None:
    data = load_input("complete_trade")
    direct = make_candles(data["candles"])
    publish_batch(_klines_from_candles(direct), interval="1m", symbol="BTCUSDT", raw_root=tmp_path)

    result = read_candles(
        tmp_path,
        "BTCUSDT",
        parse_utc("2026-01-05T10:00:30+00:00"),
        parse_utc("2026-01-05T10:03:10+00:00"),
    )
    assert isinstance(result, CandleReadResult)
    assert result.rejected == 0
    assert [c.open_time_utc for c in result.candles] == [c.open_time_utc for c in direct]
    assert [(c.high, c.low) for c in result.candles] == [(c.high, c.low) for c in direct]
    assert all(c.interval == "1m" for c in result.candles)

    outcome = normalize_backtest([make_trade_record(**data["trade"])]).outcomes[0]
    from_store = compute_trade_excursion(outcome, result.candles)
    from_direct = compute_trade_excursion(outcome, direct)
    assert from_store.incomplete_reason is None
    assert (from_store.mfe_price, from_store.mae_price) == (
        from_direct.mfe_price,
        from_direct.mae_price,
    )
    assert (from_store.mfe_r, from_store.mae_r) == (from_direct.mfe_r, from_direct.mae_r)


def test_read_candles_spans_day_partitions_and_filters_the_window(tmp_path: Path) -> None:
    start = datetime(2026, 1, 5, 23, 58, tzinfo=UTC)
    rows = [
        {
            "symbol": "BTCUSDT",
            "open_time_utc": (start + timedelta(minutes=i)).isoformat(),
            "high": "101.00",
            "low": "100.00",
        }
        for i in range(5)
    ]
    publish_batch(
        _klines_from_candles(make_candles(rows)),
        interval="1m",
        symbol="BTCUSDT",
        raw_root=tmp_path,
    )
    result = read_candles(
        tmp_path,
        "BTCUSDT",
        datetime(2026, 1, 5, 23, 59, 30, tzinfo=UTC),
        datetime(2026, 1, 6, 0, 1, tzinfo=UTC),
    )
    assert [c.open_time_utc for c in result.candles] == [
        datetime(2026, 1, 5, 23, 59, tzinfo=UTC),
        datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 6, 0, 1, tzinfo=UTC),
    ]


def test_read_candles_missing_partition_returns_empty_never_fabricates(tmp_path: Path) -> None:
    result = read_candles(
        tmp_path,
        "BTCUSDT",
        datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        datetime(2026, 1, 7, 10, 0, tzinfo=UTC),
    )
    assert result == CandleReadResult(candles=(), rejected=0)


def test_read_candles_gap_inside_a_day_is_not_forward_filled(tmp_path: Path) -> None:
    rows = [
        {
            "symbol": "BTCUSDT",
            "open_time_utc": f"2026-01-05T10:0{i}:00+00:00",
            "high": "101.00",
            "low": "100.00",
        }
        for i in (0, 3)
    ]
    publish_batch(
        _klines_from_candles(make_candles(rows)),
        interval="1m",
        symbol="BTCUSDT",
        raw_root=tmp_path,
    )
    result = read_candles(
        tmp_path,
        "BTCUSDT",
        datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        datetime(2026, 1, 5, 10, 5, tzinfo=UTC),
    )
    assert [c.open_time_utc.minute for c in result.candles] == [0, 3]


def test_read_candles_rejects_unsafe_symbols_and_naive_bounds(tmp_path: Path) -> None:
    start = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="symbol"):
        read_candles(tmp_path, "../BTCUSDT", start, start)
    with pytest.raises(ValueError, match="UTC"):
        read_candles(tmp_path, "BTCUSDT", datetime(2026, 1, 5, 10, 0), start)


def test_read_candles_counts_an_unreadable_partition_as_rejected(tmp_path: Path) -> None:
    from src.data.store import partition_file

    path = partition_file(tmp_path, "1m", "BTCUSDT", datetime(2026, 1, 5, tzinfo=UTC).date())
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a parquet file")
    result = read_candles(
        tmp_path,
        "BTCUSDT",
        datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        datetime(2026, 1, 5, 11, 0, tzinfo=UTC),
    )
    assert result.candles == ()
    assert result.rejected == 1


# --------------------------------------------------------------------------- #
# Optional live-PG integration (skipped without TEST_DATABASE_URL)
# --------------------------------------------------------------------------- #


# psycopg's async mode cannot run on the Windows default (Proactor) event loop.
_LOOP_FACTORY = asyncio.SelectorEventLoop if sys.platform == "win32" else None


def _is_throwaway_database(url: str) -> bool:
    """True only for a database whose name ends in `_test` (the test drops every table)."""
    try:
        name = make_url(url).database
    except Exception:
        return False
    return isinstance(name, str) and name.endswith("_test")


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("postgresql+psycopg://u:p@localhost:5432/trading_test", True),
        ("postgresql+psycopg://u:p@localhost:5432/trading", False),
        ("postgresql+psycopg://u:p@localhost:5432/test_trading", False),
        ("postgresql+psycopg://u:p@localhost:5432/", False),
        ("not a url", False),
    ],
)
def test_pg_integration_only_runs_against_a_throwaway_test_database(
    url: str, allowed: bool
) -> None:
    """WR-14: TEST_DATABASE_URL pointing at a dev/operational database is refused."""
    assert _is_throwaway_database(url) is allowed


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="live-PG analytics store test requires TEST_DATABASE_URL",
)
def test_pg_append_and_reread_one_kill_gate_event() -> None:
    from src.db.models import dispose_engine, make_session_factory

    url = os.environ["TEST_DATABASE_URL"]
    if not _is_throwaway_database(url):
        pytest.fail(
            "TEST_DATABASE_URL must name a throwaway database ending in '_test': "
            "this test creates and then drops every table"
        )
    sync_engine = create_engine(url)
    Base.metadata.create_all(sync_engine)
    event = _event(entity_id="KILL_GATE_PG_TEST")

    async def scenario() -> JournalReadResult:
        factory = make_session_factory(url)
        try:
            async with factory() as session:
                await append_kill_gate_event(session, event)
                await append_kill_gate_event(session, event)
                return await read_journal_events(session, event_types=[KGE])
        finally:
            await dispose_engine(url)

    try:
        result = asyncio.run(scenario(), loop_factory=_LOOP_FACTORY)
        assert [e.journal_event_id for e in result.events] == [event.journal_event_id]
        assert result.rejected == 0
    finally:
        Base.metadata.drop_all(sync_engine)
        sync_engine.dispose()
