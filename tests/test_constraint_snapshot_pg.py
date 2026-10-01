"""PgPlanConstraintSnapshotStore: write-once evidence, verified on read (17-13, EXEC-04, D-18).

Pins, against a real PostgreSQL server (each test on a generated `t17_<hex>_test` clone built by
`alembic upgrade head`):

  - the exact snapshot used for sizing is stored per trade plan as canonical JSON plus its
    sha256 and read back equal; the stored JSON carries no float literal;
  - recording is write-once: replaying the same snapshot is a no-op, a different snapshot for
    the same plan is `RowConflict` and leaves the stored row untouched; a snapshot for a missing
    plan is `ParentRowMissing`;
  - every read recomputes the digest; a row whose digest (or denormalized column) disagrees with
    its JSON fails closed with `RowConflict` instead of returning data;
  - `is_valid_for_live` is False for a missing plan, for today's INCOMPLETE snapshots (UNKNOWN
    margin type / leverage / equity), and for stale or future-dated captures, and True only for a
    COMPLETE fresh snapshot;
  - the append-only trigger refuses an UPDATE that bypasses the store.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from src.domain.registry import ParameterSet
from src.execution.constraint_snapshot import (
    UNKNOWN,
    ExchangeFilterExtras,
    PlanConstraintSnapshot,
    build_plan_constraint_snapshot,
    canonical_json,
    snapshot_sha256,
    ttl_from_parameter_set,
)
from src.persistence.engine import make_sync_engine
from src.persistence.errors import ParentRowMissing, RowConflict
from src.persistence.snapshots import PgPlanConstraintSnapshotStore
from src.persistence.uow import OperationalDatabase
from src.risk.types import ConstraintSnapshot

from tests.support.pg_rows import expect_db_error, hexid, insert_and_commit, make_plan, make_signal

OBSERVED = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
CAPTURED = datetime(2026, 9, 30, 12, 0, 5, tzinfo=UTC)
PLAN_1 = hexid(0x1001)
PLAN_2 = hexid(0x1002)


@pytest.fixture
def engine(pg_db: str) -> Iterator[Engine]:
    eng = make_sync_engine(pg_db)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def db(engine: Engine) -> OperationalDatabase:
    return OperationalDatabase(engine)


@pytest.fixture
def store(db: OperationalDatabase) -> PgPlanConstraintSnapshotStore:
    return PgPlanConstraintSnapshotStore(db)


@pytest.fixture
def plans(engine: Engine) -> None:
    """Signal 1 with trade plans 1 and 2 committed (the FK parents)."""
    insert_and_commit(engine, make_signal(1), make_plan(1, 1), make_plan(2, 1))


def _constraints() -> ConstraintSnapshot:
    return ConstraintSnapshot(
        symbol="BTCUSDT",
        price_tick_size=Decimal("0.10"),
        quantity_step_size=Decimal("0.001"),
        min_quantity=Decimal("0.001"),
        min_notional=Decimal("50"),
        metadata_observed_at_utc=OBSERVED,
    )


def _extras() -> ExchangeFilterExtras:
    return ExchangeFilterExtras(
        market_lot_min_quantity=Decimal("0.001"),
        market_lot_max_quantity=Decimal("120"),
        market_lot_step_size=Decimal("0.001"),
        percent_price_multiplier_up=Decimal("1.0500"),
        percent_price_multiplier_down=Decimal("0.9500"),
        percent_price_multiplier_decimals=4,
    )


def incomplete(plan_id: str = PLAN_1, **overrides: Any) -> PlanConstraintSnapshot:
    """Today's snapshot: margin type, leverage and equity are UNKNOWN until Phases 21-22."""
    kwargs: dict[str, Any] = {
        "max_quantity": Decimal("1000"),
        "working_type": "MARK_PRICE",
        "captured_at_utc": CAPTURED,
    }
    kwargs.update(overrides)
    return build_plan_constraint_snapshot(plan_id, _constraints(), _extras(), **kwargs)


def complete(plan_id: str = PLAN_1, **overrides: Any) -> PlanConstraintSnapshot:
    kwargs: dict[str, Any] = {
        "margin_type": "ISOLATED",
        "leverage": 5,
        "equity_used": Decimal("1000.50"),
    }
    kwargs.update(overrides)
    return incomplete(plan_id, **kwargs)


def _params(ttl_seconds: int = 900) -> ParameterSet:
    return ParameterSet(
        strategy_id="breakout-retest",
        strategy_version="v1",
        parameter_set_id="test",
        parameter_set_hash="0" * 64,
        params={"constraint_snapshot_ttl_seconds": ttl_seconds},
    )


def _raw_row(engine: Engine, plan_id: str) -> dict[str, Any]:
    with engine.connect() as conn:
        row = (
            conn.execute(
                text("SELECT * FROM plan_constraint_snapshots WHERE trade_plan_id = :p"),
                {"p": plan_id},
            )
            .mappings()
            .one()
        )
    return dict(row)


def _insert_raw(engine: Engine, snapshot: PlanConstraintSnapshot, **overrides: Any) -> None:
    """Insert a row bypassing the store (to plant a row the store would never write)."""
    values: dict[str, Any] = {
        "trade_plan_id": snapshot.trade_plan_id,
        "symbol": snapshot.symbol,
        "working_type": snapshot.working_type,
        "margin_type": snapshot.margin_type or UNKNOWN,
        "leverage": UNKNOWN if snapshot.leverage is None else str(snapshot.leverage),
        "equity_used": UNKNOWN if snapshot.equity_used is None else str(snapshot.equity_used),
        "live_inputs_status": snapshot.live_inputs_status.value,
        "constraints_observed_at_utc": snapshot.constraints_observed_at_utc,
        "captured_at_utc": snapshot.captured_at_utc,
        "snapshot_json": canonical_json(snapshot),
        "snapshot_sha256": snapshot_sha256(snapshot),
    }
    values.update(overrides)
    columns = ", ".join(values)
    binds = ", ".join(f":{name}" for name in values)
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO plan_constraint_snapshots ({columns}) VALUES ({binds})"), values
        )


# --------------------------------------------------------------------------- #
# record / get
# --------------------------------------------------------------------------- #


def test_record_then_get_round_trips_with_sha_and_no_float(
    store: PgPlanConstraintSnapshotStore, engine: Engine, plans: None
) -> None:
    snap = complete()
    store.record(snap)

    assert store.get(PLAN_1) == snap

    row = _raw_row(engine, PLAN_1)
    assert row["snapshot_sha256"] == snapshot_sha256(snap)
    assert row["snapshot_json"] == canonical_json(snap)
    assert not re.search(r":-?\d+\.\d", row["snapshot_json"]), "float literal in stored JSON"
    assert (row["symbol"], row["working_type"]) == ("BTCUSDT", "MARK_PRICE")
    assert (row["margin_type"], row["leverage"], row["equity_used"]) == (
        "ISOLATED",
        "5",
        "1000.50",
    )
    assert row["live_inputs_status"] == "COMPLETE"


def test_incomplete_snapshot_is_stored_with_the_unknown_sentinel(
    store: PgPlanConstraintSnapshotStore, engine: Engine, plans: None
) -> None:
    snap = incomplete()
    store.record(snap)

    assert store.get(PLAN_1) == snap
    row = _raw_row(engine, PLAN_1)
    assert (row["margin_type"], row["leverage"], row["equity_used"]) == (UNKNOWN,) * 3
    assert row["live_inputs_status"] == "INCOMPLETE"


def test_get_of_an_unknown_plan_is_none(store: PgPlanConstraintSnapshotStore, plans: None) -> None:
    assert store.get(PLAN_2) is None


def test_replaying_the_same_snapshot_is_a_no_op(
    store: PgPlanConstraintSnapshotStore, engine: Engine, plans: None
) -> None:
    snap = complete()
    store.record(snap)
    before = _raw_row(engine, PLAN_1)

    store.record(snap)

    assert _raw_row(engine, PLAN_1) == before
    assert store.get(PLAN_1) == snap


def test_a_different_snapshot_for_the_same_plan_is_a_row_conflict(
    store: PgPlanConstraintSnapshotStore, engine: Engine, plans: None
) -> None:
    store.record(complete())
    before = _raw_row(engine, PLAN_1)

    with pytest.raises(RowConflict):
        store.record(complete(equity_used=Decimal("999")))

    assert _raw_row(engine, PLAN_1) == before


def test_a_snapshot_for_a_missing_plan_is_parent_row_missing(
    store: PgPlanConstraintSnapshotStore, plans: None
) -> None:
    with pytest.raises(ParentRowMissing):
        store.record(complete(hexid(0x1999)))
    assert store.get(hexid(0x1999)) is None


def test_record_joins_the_callers_unit_of_work(
    db: OperationalDatabase, store: PgPlanConstraintSnapshotStore, plans: None
) -> None:
    class Abort(Exception):
        pass

    with pytest.raises(Abort), db.transaction() as tx:
        store.record(complete(), tx=tx)
        raise Abort

    assert store.get(PLAN_1) is None


# --------------------------------------------------------------------------- #
# Hash verification on read (fail closed)
# --------------------------------------------------------------------------- #


def test_a_stored_sha_that_does_not_match_the_json_fails_closed(
    store: PgPlanConstraintSnapshotStore, engine: Engine, plans: None
) -> None:
    _insert_raw(engine, complete(), snapshot_sha256="0" * 64)

    with pytest.raises(RowConflict):
        store.get(PLAN_1)
    assert (
        store.is_valid_for_live(PLAN_1, now_utc=CAPTURED, ttl=ttl_from_parameter_set(_params()))
        is False
    )


def test_a_denormalized_column_that_disagrees_with_the_json_fails_closed(
    store: PgPlanConstraintSnapshotStore, engine: Engine, plans: None
) -> None:
    _insert_raw(engine, complete(), symbol="ETHUSDT")

    with pytest.raises(RowConflict):
        store.get(PLAN_1)


def test_stored_json_that_is_not_a_valid_snapshot_fails_closed(
    store: PgPlanConstraintSnapshotStore, engine: Engine, plans: None
) -> None:
    _insert_raw(engine, complete(), snapshot_json='{"symbol":"BTCUSDT"}')

    with pytest.raises(ValueError, match="keys differ"):
        store.get(PLAN_1)


def test_the_append_only_trigger_refuses_an_update_that_bypasses_the_store(
    store: PgPlanConstraintSnapshotStore, engine: Engine, plans: None
) -> None:
    store.record(complete())

    with expect_db_error(), engine.begin() as conn:
        conn.execute(text("UPDATE plan_constraint_snapshots SET symbol = 'X'"))

    assert store.get(PLAN_1) == complete()


# --------------------------------------------------------------------------- #
# Live validity
# --------------------------------------------------------------------------- #


def test_is_valid_for_live_is_false_for_a_missing_plan(
    store: PgPlanConstraintSnapshotStore, plans: None
) -> None:
    ttl = ttl_from_parameter_set(_params())
    assert store.is_valid_for_live(PLAN_2, now_utc=CAPTURED, ttl=ttl) is False


def test_is_valid_for_live_is_false_for_todays_incomplete_snapshot(
    store: PgPlanConstraintSnapshotStore, plans: None
) -> None:
    store.record(incomplete())
    ttl = ttl_from_parameter_set(_params())
    assert store.is_valid_for_live(PLAN_1, now_utc=CAPTURED, ttl=ttl) is False


def test_is_valid_for_live_is_true_only_for_a_complete_fresh_snapshot(
    store: PgPlanConstraintSnapshotStore, plans: None
) -> None:
    store.record(complete())
    ttl = ttl_from_parameter_set(_params(900))

    assert store.is_valid_for_live(PLAN_1, now_utc=OBSERVED + timedelta(seconds=60), ttl=ttl)
    # Exactly the TTL is still valid; one second past it is stale.
    assert store.is_valid_for_live(PLAN_1, now_utc=OBSERVED + ttl, ttl=ttl)
    assert not store.is_valid_for_live(
        PLAN_1, now_utc=OBSERVED + ttl + timedelta(seconds=1), ttl=ttl
    )


def test_is_valid_for_live_is_false_for_a_future_dated_capture(
    store: PgPlanConstraintSnapshotStore, plans: None
) -> None:
    store.record(complete())
    ttl = ttl_from_parameter_set(_params())
    assert not store.is_valid_for_live(PLAN_1, now_utc=OBSERVED - timedelta(seconds=1), ttl=ttl)


def test_a_replay_with_a_different_capture_time_is_a_conflict(
    store: PgPlanConstraintSnapshotStore, plans: None
) -> None:
    snap = complete()
    store.record(snap)
    with pytest.raises(RowConflict):
        store.record(replace(snap, captured_at_utc=CAPTURED + timedelta(seconds=1)))
