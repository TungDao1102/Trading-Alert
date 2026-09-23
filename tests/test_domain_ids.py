"""Tests for the content-hash ID constructors (Phase 3, plan 03-01).

Per D-03: SignalId = hash(strategyVersion + parameterSetId + symbol +
source_timeframe + source_candle_close_utc + setup fingerprint). Plan/order
IDs derive from their parent signal hash plus a fixed discriminator.

TDD discipline: RED → GREEN. These tests are the RED phase — they MUST
fail until `src/domain/canonical.py` and `src/domain/ids.py` are
implemented.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from src.domain.ids import derive_child_id, make_signal_id

# --------------------------------------------------------------------------- #
# Test 1 — make_signal_id returns a stable 64-hex string.
# --------------------------------------------------------------------------- #


def test_make_signal_id_returns_64_hex_string() -> None:
    """Beh. 1: make_signal_id returns a 64-character lowercase hex string.

    SHA256 hexdigest is always 64 hex chars; this is the canonical
    content-hash ID format.
    """
    signal_id = make_signal_id(
        strategy_id="trend-pullback",
        strategy_version="v1.0.0",
        parameter_set_id="baseline-v1",
        symbol="BTCUSDT",
        source_timeframe="1h",
        source_candle_close_utc=datetime(2026, 9, 19, 0, 0, tzinfo=UTC),
        setup_fingerprint="trend-pullback:long",
    )
    assert isinstance(signal_id, str)
    assert len(signal_id) == 64
    assert all(c in "0123456789abcdef" for c in signal_id)


# --------------------------------------------------------------------------- #
# Test 2 — make_signal_id is deterministic across key orderings.
# --------------------------------------------------------------------------- #


def test_make_signal_id_is_deterministic_across_key_orderings() -> None:
    """Beh. 2: same logical inputs always produce the same digest.

    The canonicalizer sorts dict keys before hashing, so the order in
    which the caller passes keyword arguments does not affect the
    digest. (Python keyword arguments are already ordered by name, but
    this test pins the contract.)
    """
    kwargs = {
        "strategy_id": "trend-pullback",
        "strategy_version": "v1.0.0",
        "parameter_set_id": "baseline-v1",
        "symbol": "BTCUSDT",
        "source_timeframe": "1h",
        "source_candle_close_utc": datetime(2026, 9, 19, 0, 0, tzinfo=UTC),
        "setup_fingerprint": "trend-pullback:long",
    }
    id_a = make_signal_id(**kwargs)
    id_b = make_signal_id(**kwargs)
    assert id_a == id_b


# --------------------------------------------------------------------------- #
# Test 3 — naive datetime raises ValueError.
# --------------------------------------------------------------------------- #


def test_make_signal_id_rejects_naive_datetime() -> None:
    """Beh. 3: naive datetime in source_candle_close_utc raises ValueError.

    D-12: UTC `datetime` internally; naive datetimes are forbidden at
    the canonical-hash boundary.
    """
    with pytest.raises(ValueError, match="naive datetime"):
        make_signal_id(
            strategy_id="trend-pullback",
            strategy_version="v1.0.0",
            parameter_set_id="baseline-v1",
            symbol="BTCUSDT",
            source_timeframe="1h",
            source_candle_close_utc=datetime(2026, 9, 19, 0, 0),  # naive!
            setup_fingerprint="trend-pullback:long",
        )


# --------------------------------------------------------------------------- #
# Test 4 — float input raises TypeError.
# --------------------------------------------------------------------------- #


def test_make_signal_id_rejects_float_input() -> None:
    """Beh. 4: float in any input raises TypeError.

    D-12: float is banned for exchange-sensitive values. The
    canonicalizer rejects float loudly instead of serializing it.
    """
    with pytest.raises(TypeError, match="float"):
        make_signal_id(
            strategy_id="trend-pullback",
            strategy_version="v1.0.0",
            parameter_set_id="baseline-v1",
            symbol="BTCUSDT",
            source_timeframe="1h",
            source_candle_close_utc=datetime(2026, 9, 19, 0, 0, tzinfo=UTC),
            setup_fingerprint=1.5,  # float!
        )


# --------------------------------------------------------------------------- #
# Test 5 — set input raises TypeError.
# --------------------------------------------------------------------------- #


def test_make_signal_id_rejects_set_input() -> None:
    """Beh. 5: set in any input raises TypeError.

    Sets are unordered; the canonicalizer refuses to silently sort
    them. Use a sorted list instead.
    """
    with pytest.raises(TypeError, match="unordered"):
        make_signal_id(
            strategy_id="trend-pullback",
            strategy_version="v1.0.0",
            parameter_set_id="baseline-v1",
            symbol="BTCUSDT",
            source_timeframe="1h",
            source_candle_close_utc=datetime(2026, 9, 19, 0, 0, tzinfo=UTC),
            setup_fingerprint={"a", "b"},  # set!
        )


# --------------------------------------------------------------------------- #
# Test 6 — different inputs produce different IDs.
# --------------------------------------------------------------------------- #


def test_make_signal_id_different_inputs_produce_different_ids() -> None:
    """Beh. 6: changing any input field changes the digest.

    Pins the binding superset from D-03: every input field is part of
    the identity.
    """
    base_kwargs = {
        "strategy_id": "trend-pullback",
        "strategy_version": "v1.0.0",
        "parameter_set_id": "baseline-v1",
        "symbol": "BTCUSDT",
        "source_timeframe": "1h",
        "source_candle_close_utc": datetime(2026, 9, 19, 0, 0, tzinfo=UTC),
        "setup_fingerprint": "trend-pullback:long",
    }
    base_id = make_signal_id(**base_kwargs)

    # Change each field in turn; each must produce a different digest.
    for changed_field, changed_value in [
        ("strategy_id", "mean-reversion"),
        ("strategy_version", "v1.0.1"),
        ("parameter_set_id", "baseline-v2"),
        ("symbol", "ETHUSDT"),
        ("source_timeframe", "4h"),
        (
            "source_candle_close_utc",
            datetime(2026, 9, 19, 1, 0, tzinfo=UTC),
        ),
        ("setup_fingerprint", "trend-pullback:short"),
    ]:
        kwargs = dict(base_kwargs)
        kwargs[changed_field] = changed_value
        assert make_signal_id(**kwargs) != base_id, (
            f"changing {changed_field} should change the digest"
        )


# --------------------------------------------------------------------------- #
# Test 7 — derive_child_id is deterministic and discriminator-sensitive.
# --------------------------------------------------------------------------- #


def test_derive_child_id_is_deterministic() -> None:
    """Beh. 7: derive_child_id returns a stable 64-hex string.

    Plan/order IDs derive from their parent signal hash plus a fixed
    discriminator (e.g. "trade_plan:v1", "order:entry").
    """
    parent = "a" * 64
    child_id = derive_child_id(parent_signal_id=parent, discriminator="trade_plan:v1")
    assert isinstance(child_id, str)
    assert len(child_id) == 64
    assert all(c in "0123456789abcdef" for c in child_id)


def test_derive_child_id_different_discriminators_produce_different_ids() -> None:
    """Beh. 7b: different discriminators produce different child IDs.

    Pins the contract that the discriminator is part of the identity.
    """
    parent = "a" * 64
    plan_id = derive_child_id(parent_signal_id=parent, discriminator="trade_plan:v1")
    order_id = derive_child_id(parent_signal_id=parent, discriminator="order:entry")
    assert plan_id != order_id


def test_derive_child_id_different_parents_produce_different_ids() -> None:
    """Beh. 7c: different parent signal IDs produce different child IDs."""
    plan_a = derive_child_id(parent_signal_id="a" * 64, discriminator="trade_plan:v1")
    plan_b = derive_child_id(parent_signal_id="b" * 64, discriminator="trade_plan:v1")
    assert plan_a != plan_b


# --------------------------------------------------------------------------- #
# Test 8 — Decimal precision preserved (Decimal("1.50") != Decimal("1.5")).
# --------------------------------------------------------------------------- #


def test_decimal_precision_preserved_in_canonical_hash() -> None:
    """Beh. 8: Decimal("1.50") and Decimal("1.5") produce different digests.

    The canonicalizer renders Decimal via str() (full precision
    preserved). This is documented behavior, not a bug — different
    Decimal representations are different inputs.
    """
    # Use the canonical_bytes helper indirectly via make_signal_id by
    # embedding a Decimal in the setup_fingerprint (which is a string
    # in the public API). Instead, exercise the canonicalizer directly
    # via a small wrapper: build two payloads with different Decimal
    # representations and confirm the digests differ.
    from src.domain.canonical import sha256_hex

    digest_a = sha256_hex({"value": Decimal("1.50")})
    digest_b = sha256_hex({"value": Decimal("1.5")})
    assert digest_a != digest_b


# --------------------------------------------------------------------------- #
# Test 9 — strategy_id is bound into the digest (CR-01).
# --------------------------------------------------------------------------- #


def test_make_signal_id_binds_strategy_id() -> None:
    """Beh. 9: same version/id/symbol/time/close/fingerprint under two
    strategy_id values yields different digests (CR-01).

    Without strategy_id binding, `trend-pullback` and a future
    `mean-reversion` strategy sharing every other field would collide
    to the same signal_id.
    """
    kwargs = {
        "strategy_version": "v1.0.0",
        "parameter_set_id": "baseline-v1",
        "symbol": "BTCUSDT",
        "source_timeframe": "1h",
        "source_candle_close_utc": datetime(2026, 9, 19, 0, 0, tzinfo=UTC),
        "setup_fingerprint": "trend-pullback:long",
    }
    id_a = make_signal_id(strategy_id="trend-pullback", **kwargs)
    id_b = make_signal_id(strategy_id="mean-reversion", **kwargs)
    assert id_a != id_b
