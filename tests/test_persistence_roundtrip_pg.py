"""Seeded round-trip property: every mapper pair survives real PostgreSQL (17-10, D-26, SC1).

For each of Signal, TradePlan, Order, Fill and Position, 25 cases drawn from
`random.Random(17)` (stdlib, fixed seed, no hypothesis) go through
`PgTradingEntityStore` insert and read-back and must come back as EQUAL domain objects. The
generators cover what the unit tests of the mappers cannot reach without a server:

  - GLOSSARY-valid enum members for every status (inserts write the status as given; the
    transition rules are the subject of `test_persistence_transitions_pg.py`);
  - Decimals with 0 to 18 fractional digits (trailing zeros included), a zero order quantity,
    a signed position quantity and PnL, and one boundary case at the full NUMERIC(38,18) width;
  - `None` for every nullable field in some cases and a value in others;
  - UTC datetimes with microseconds.

Equality here is the dataclass equality, so a Decimal that PostgreSQL rounded, a datetime that
lost its microseconds, a status the mapper mistranslated or a nullable that flipped would fail
the case. The seed is fixed: a failure reproduces exactly, and the case index is in the message.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.engine import Engine
from src.domain.canonical import quantize_for_storage
from src.domain.enums import (
    OrderRole,
    OrderStatus,
    PositionStatus,
    SignalStatus,
    TradePlanStatus,
)
from src.domain.fill import Fill
from src.domain.order import Order
from src.domain.position import Position
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.persistence.engine import make_sync_engine
from src.persistence.entities import PgTradingEntityStore
from src.persistence.uow import OperationalDatabase

CASES = 25

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
SETUP_TYPES = (
    "TREND_PULLBACK_LONG",
    "TREND_PULLBACK_SHORT",
    "BREAKOUT_RETEST_LONG",
    "BREAKOUT_RETEST_SHORT",
    "RANGE_MR_LONG",
    "RANGE_MR_SHORT",
)
TIMEFRAMES = ("1m", "1h", "4h")
ENTRY_MODELS = ("LIMIT_ZONE", "MARKET")
ORDER_TYPES = ("MARKET", "LIMIT", "STOP_MARKET", "TAKE_PROFIT_MARKET", "STOP", "TAKE_PROFIT")
TIMES_IN_FORCE = ("GTC", "IOC", "FOK", "GTX")
SIDES = ("BUY", "SELL")
POSITION_SIDES = ("LONG", "SHORT", "BOTH")
NINES_38 = Decimal("99999999999999999999.999999999999999999")  # widest NUMERIC(38,18) value


def _rng() -> random.Random:
    """The one generator of this module: stdlib, fixed seed (D-26)."""
    return random.Random(17)


@pytest.fixture
def engine(pg_db: str) -> Iterator[Engine]:
    eng = make_sync_engine(pg_db)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def store(engine: Engine) -> PgTradingEntityStore:
    return PgTradingEntityStore(OperationalDatabase(engine))


# --------------------------------------------------------------------------- #
# Generators.
# --------------------------------------------------------------------------- #


def _hex64(rng: random.Random) -> str:
    return f"{rng.getrandbits(256):064x}"


def _decimal(rng: random.Random, *, signed: bool = False, zero: bool = False) -> Decimal:
    """A Decimal with 0..18 fractional digits and up to 12 integer digits, built exactly.

    Positive unless `signed`; `zero` allows an exact 0 in some cases.
    """
    frac = rng.randint(0, 18)
    digits = rng.randint(1, 12) + frac
    unscaled = rng.randint(1, 10**digits - 1)
    if zero and rng.random() < 0.25:
        unscaled = 0
    value = Decimal(f"{unscaled}E-{frac}")
    if signed and rng.random() < 0.5:
        value = -value
    assert value == quantize_for_storage(value)  # the generator never leaves the storage scale
    return value


def _utc(rng: random.Random) -> datetime:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    return base + timedelta(
        seconds=rng.randint(0, 3 * 365 * 24 * 3600), microseconds=rng.randint(0, 999_999)
    )


def _opt_utc(rng: random.Random) -> datetime | None:
    return _utc(rng) if rng.random() < 0.5 else None


def _signal(rng: random.Random, n: int) -> Signal:
    return Signal(
        signal_id=_hex64(rng),
        strategy_id=rng.choice(("trend-pullback", "breakout-retest", "range-mr")),
        strategy_version=f"v{rng.randint(1, 9)}.{rng.randint(0, 9)}.{rng.randint(0, 9)}",
        parameter_set_id=f"baseline-v{rng.randint(1, 5)}",
        parameter_set_hash=_hex64(rng),
        symbol=rng.choice(SYMBOLS),
        direction=rng.choice(("LONG", "SHORT")),
        setup_type=rng.choice(SETUP_TYPES),
        source_timeframe=rng.choice(TIMEFRAMES),
        source_candle_close_utc=_utc(rng),
        detected_at_utc=_utc(rng),
        status=rng.choice(list(SignalStatus)),
        expires_at_utc=_utc(rng),
        invalidated_at_utc=_opt_utc(rng),
    )


def _plan(rng: random.Random, n: int, signal_id: str) -> TradePlan:
    prices = {
        "entry_min_price": _decimal(rng),
        "entry_max_price": _decimal(rng),
        "stop_loss_price": _decimal(rng),
    }
    if n == 0:
        prices["entry_max_price"] = NINES_38  # boundary: full NUMERIC(38,18) width
    return TradePlan(
        trade_plan_id=_hex64(rng),
        signal_id=signal_id,
        trade_plan_version=f"v{rng.randint(1, 9)}",
        entry_model=rng.choice(ENTRY_MODELS),
        take_profit_json=rng.choice(("[]", '{"tp1":"1.5"}', '{"tp1":"2","tp2":"3"}')),
        invalidation_rule_json=rng.choice(("{}", '{"basis":"CANDLE_CLOSE"}')),
        expiry_utc=_utc(rng),
        expected_rr_json=rng.choice(("{}", '{"tp1_rr":"2.5"}')),
        risk_rate=_decimal(rng),
        risk_budget=_decimal(rng),
        suggested_quantity=_decimal(rng, zero=True),
        quantity_before_rounding=_decimal(rng, zero=True),
        quantity_after_rounding=_decimal(rng, zero=True),
        quantization_decision=rng.choice(("DEFERRED_TO_RISK", "ACCEPTED", "REJECTED")),
        plan_hash=_hex64(rng),
        status=rng.choice(list(TradePlanStatus)),
        created_at_utc=_utc(rng),
        **prices,
    )


def _position(rng: random.Random, n: int) -> Position:
    return Position(
        position_id=_hex64(rng),
        symbol=rng.choice(SYMBOLS),
        position_side=rng.choice(POSITION_SIDES),
        mode=rng.choice(("ONE_WAY", "HEDGE")),
        quantity=_decimal(rng, signed=True, zero=True),  # signed in one-way mode
        entry_price=_decimal(rng),
        break_even_price=_decimal(rng),
        unrealized_pnl=_decimal(rng, signed=True, zero=True),
        realized_pnl=_decimal(rng, signed=True, zero=True),
        opened_at_utc=_utc(rng),
        updated_at_utc=_utc(rng),
        closed_at_utc=_opt_utc(rng),
        status=rng.choice(list(PositionStatus)),
    )


def _order(
    rng: random.Random,
    n: int,
    plan_ids: list[str],
    position_ids: list[str],
    earlier_order_ids: list[str],
) -> Order:
    has_client = rng.random() < 0.7
    has_algo = not has_client or rng.random() < 0.3
    return Order(
        order_id=_hex64(rng),
        trade_plan_id=rng.choice(plan_ids) if plan_ids and rng.random() < 0.7 else None,
        position_id=rng.choice(position_ids) if position_ids and rng.random() < 0.5 else None,
        parent_order_id=(
            rng.choice(earlier_order_ids) if earlier_order_ids and rng.random() < 0.4 else None
        ),
        order_role=rng.choice([role.value for role in OrderRole]),
        exchange="BINANCE_USDM",
        symbol=rng.choice(SYMBOLS),
        side=rng.choice(SIDES),
        position_side=rng.choice(POSITION_SIDES),
        order_type=rng.choice(ORDER_TYPES),
        time_in_force=rng.choice(TIMES_IN_FORCE),
        quantity=_decimal(rng, zero=True),  # includes 0 (a closePosition leg carries none)
        price=_decimal(rng) if rng.random() < 0.6 else None,
        stop_price=_decimal(rng) if rng.random() < 0.5 else None,
        close_position=rng.random() < 0.3,
        reduce_only=rng.random() < 0.3,
        client_order_id=f"x-{rng.getrandbits(128):032x}EN" if has_client else None,
        exchange_order_id=str(rng.randint(10**9, 10**12)) if rng.random() < 0.5 else None,
        algo_client_id=f"xa-{rng.getrandbits(124):031x}SL" if has_algo else None,
        exchange_status=rng.choice(("NEW", "PARTIALLY_FILLED", "FILLED", "CANCELED", "EXPIRED")),
        local_status=rng.choice(list(OrderStatus)),
        submitted_at_utc=_utc(rng),
        updated_at_utc=_utc(rng),
        canceled_at_utc=_opt_utc(rng),
    )


def _fill(rng: random.Random, n: int, order_id: str) -> Fill:
    return Fill(
        fill_id=_hex64(rng),
        order_id=order_id,
        exchange_trade_id=str(rng.randint(10**6, 10**12)),
        symbol=rng.choice(SYMBOLS),
        side=rng.choice(SIDES),
        position_side=rng.choice(POSITION_SIDES),
        fill_price=_decimal(rng),
        fill_quantity=_decimal(rng),
        quote_quantity=_decimal(rng, zero=True),
        commission=_decimal(rng, zero=True),
        commission_asset=rng.choice(("USDT", "BNB", "BUSD")),
        realized_pnl=_decimal(rng, signed=True, zero=True),
        fill_time_utc=_utc(rng),
        is_maker=rng.random() < 0.5,
    )


# --------------------------------------------------------------------------- #
# Properties.
# --------------------------------------------------------------------------- #


def test_signal_round_trips_through_postgresql(store: PgTradingEntityStore) -> None:
    rng = _rng()
    for n in range(CASES):
        original = _signal(rng, n)
        store.insert_signal(original)
        assert store.get_signal(original.signal_id) == original, f"signal case {n}"


def test_trade_plan_round_trips_through_postgresql(store: PgTradingEntityStore) -> None:
    rng = _rng()
    for n in range(CASES):
        parent = _signal(rng, n)
        store.insert_signal(parent)
        original = _plan(rng, n, parent.signal_id)
        store.insert_trade_plan(original)
        stored = store.get_trade_plan(original.trade_plan_id)
        assert stored == original, f"trade plan case {n}"
        assert stored is not None
        assert stored.entry_max_price == original.entry_max_price


def test_order_round_trips_through_postgresql(store: PgTradingEntityStore) -> None:
    rng = _rng()
    plan_ids: list[str] = []
    for n in range(5):
        parent = _signal(rng, n)
        store.insert_signal(parent)
        plan = _plan(rng, n, parent.signal_id)
        store.insert_trade_plan(plan)
        plan_ids.append(plan.trade_plan_id)
    position_ids: list[str] = []
    for n in range(5):
        position = _position(rng, n)
        store.insert_position(position)
        position_ids.append(position.position_id)
    order_ids: list[str] = []
    for n in range(CASES):
        original = _order(rng, n, plan_ids, position_ids, order_ids)
        store.insert_order(original)
        assert store.get_order(original.order_id) == original, f"order case {n}"
        order_ids.append(original.order_id)


def test_zero_quantity_order_round_trips(store: PgTradingEntityStore) -> None:
    """A closePosition leg carries no quantity: 0 must come back as 0 (not None, not error)."""
    rng = _rng()
    order = _order(rng, 0, [], [], [])
    zero = replace(order, quantity=Decimal("0"))
    store.insert_order(zero)
    assert store.get_order(zero.order_id) == zero


def test_fill_round_trips_through_postgresql(store: PgTradingEntityStore) -> None:
    rng = _rng()
    order_ids: list[str] = []
    for n in range(5):
        order = _order(rng, n, [], [], order_ids)
        store.insert_order(order)
        order_ids.append(order.order_id)
    seen: dict[str, list[Fill]] = {order_id: [] for order_id in order_ids}
    used_trade_ids: set[tuple[str, str]] = set()
    for n in range(CASES):
        parent = rng.choice(order_ids)
        original = _fill(rng, n, parent)
        key = (parent, original.exchange_trade_id)
        if key in used_trade_ids:  # keep the (order_id, exchange_trade_id) key unique
            original = replace(original, exchange_trade_id=f"u{n}")
        used_trade_ids.add((parent, original.exchange_trade_id))
        store.record_fill(original)
        seen[parent].append(original)
        stored = store.list_fills_for_order(parent)
        assert original in stored, f"fill case {n}"
    for order_id, expected in seen.items():
        stored = store.list_fills_for_order(order_id)
        assert sorted(stored, key=lambda f: f.fill_id) == sorted(
            expected, key=lambda f: f.fill_id
        ), order_id


def test_position_round_trips_through_postgresql(store: PgTradingEntityStore) -> None:
    rng = _rng()
    for n in range(CASES):
        original = _position(rng, n)
        store.insert_position(original)
        assert store.get_position(original.position_id) == original, f"position case {n}"


def test_generator_is_deterministic_for_the_fixed_seed() -> None:
    first = [_signal(_rng(), 0) for _ in range(2)]
    assert first[0] == first[1]
    rng_a, rng_b = _rng(), _rng()
    assert _plan(rng_a, 3, "s") == _plan(rng_b, 3, "s")
