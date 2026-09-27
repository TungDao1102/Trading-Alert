"""Deterministic client/algo order identifier derivation (Phase 8, plan 08-03).

Per D-04: a retry, restart, or replay of an approved plan must reuse the
exchange-deduped identifier instead of minting a new one. The derivation
is a pure function of `(plan_hash, role)` over stdlib `hashlib` only.

This test pins the golden fixture pair
(`tests/fixtures/phase8/order_ids/{input,expected}.json`) and asserts:

  1. derive_client_order_id / derive_algo_client_id return fixed-length
     ASCII strings (the Binance client-order-ID charset/length rule).
  2. Same `(plan_hash, role)` always yields byte-identical IDs
     (determinism across processes).
  3. The four OrderRole values (ENTRY, STOP_LOSS, TAKE_PROFIT_1,
     TAKE_PROFIT_2) yield four distinct IDs for the same plan.
  4. Unknown role strings raise ValueError (no fallback code).
  5. The fixture pair's expected IDs match the derivation output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

PHASE8_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase8"
ORDER_IDS_FIXTURE_DIR = PHASE8_FIXTURES_DIR / "order_ids"


def _load_input() -> dict[str, Any]:
    return json.loads(
        (ORDER_IDS_FIXTURE_DIR / "input.json").read_text(encoding="utf-8")
    )


def _load_expected() -> dict[str, Any]:
    return json.loads(
        (ORDER_IDS_FIXTURE_DIR / "expected.json").read_text(encoding="utf-8")
    )


# --------------------------------------------------------------------------- #
# Beh. 1 — derivation returns a fixed-length ASCII string.
# --------------------------------------------------------------------------- #


def test_derive_client_order_id_returns_fixed_length_ascii_string() -> None:
    """Beh. 1a: derive_client_order_id returns a 36-char ASCII string.

    Binance client_order_id (and algo_client_id) accept ASCII letters
    (upper/lower), digits, hyphen, and underscore. Our derivation uses
    only hex digits, hyphens, and uppercase role-code letters so the
    charset is a strict subset.
    """
    from src.execution.order_ids import derive_client_order_id

    case = _load_input()
    cid = derive_client_order_id(
        plan_hash=case["plan_hash"], role="ENTRY"
    )
    assert isinstance(cid, str)
    assert len(cid) == 36, f"expected 36 chars, got {len(cid)}: {cid!r}"
    allowed = set(
        "0123456789"
        + "abcdefghijklmnopqrstuvwxyz"
        + "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        + "-_"
    )
    assert all(c in allowed for c in cid), (
        f"client_order_id contains non-ASCII-alnum-hyphen chars: {cid!r}"
    )


def test_derive_algo_client_id_returns_fixed_length_ascii_string() -> None:
    """Beh. 1b: derive_algo_client_id returns a 36-char ASCII string."""
    from src.execution.order_ids import derive_algo_client_id

    case = _load_input()
    aid = derive_algo_client_id(
        plan_hash=case["plan_hash"], role="STOP_LOSS"
    )
    assert isinstance(aid, str)
    assert len(aid) == 36, f"expected 36 chars, got {len(aid)}: {aid!r}"
    allowed = set(
        "0123456789"
        + "abcdefghijklmnopqrstuvwxyz"
        + "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        + "-_"
    )
    assert all(c in allowed for c in aid), (
        f"algo_client_id contains non-ASCII-alnum-hyphen chars: {aid!r}"
    )


# --------------------------------------------------------------------------- #
# Beh. 2 — determinism: same inputs always yield the same output.
# --------------------------------------------------------------------------- #


def test_derive_client_order_id_is_deterministic() -> None:
    """Beh. 2a: same (plan_hash, role) always yields the same client_order_id."""
    from src.execution.order_ids import derive_client_order_id

    case = _load_input()
    a = derive_client_order_id(plan_hash=case["plan_hash"], role="ENTRY")
    b = derive_client_order_id(plan_hash=case["plan_hash"], role="ENTRY")
    assert a == b
    assert a.encode("utf-8") == b.encode("utf-8")


def test_derive_algo_client_id_is_deterministic() -> None:
    """Beh. 2b: same (plan_hash, role) always yields the same algo_client_id."""
    from src.execution.order_ids import derive_algo_client_id

    case = _load_input()
    a = derive_algo_client_id(plan_hash=case["plan_hash"], role="ENTRY")
    b = derive_algo_client_id(plan_hash=case["plan_hash"], role="ENTRY")
    assert a == b
    assert a.encode("utf-8") == b.encode("utf-8")


# --------------------------------------------------------------------------- #
# Beh. 3 — four roles yield four distinct IDs for one plan.
# --------------------------------------------------------------------------- #


def test_four_roles_yield_four_distinct_client_order_ids() -> None:
    """Beh. 3a: ENTRY, STOP_LOSS, TAKE_PROFIT_1, TAKE_PROFIT_2 produce
    four distinct client_order_ids for the same plan_hash.
    """
    from src.execution.order_ids import derive_client_order_id

    case = _load_input()
    ids = {
        role: derive_client_order_id(plan_hash=case["plan_hash"], role=role)
        for role in case["roles"]
    }
    assert len(set(ids.values())) == 4, (
        f"roles collided: {ids}"
    )
    # Entry and protective legs never share an identifier.
    assert ids["ENTRY"] != ids["STOP_LOSS"]
    assert ids["ENTRY"] != ids["TAKE_PROFIT_1"]
    assert ids["ENTRY"] != ids["TAKE_PROFIT_2"]
    assert ids["STOP_LOSS"] != ids["TAKE_PROFIT_1"]
    assert ids["STOP_LOSS"] != ids["TAKE_PROFIT_2"]
    assert ids["TAKE_PROFIT_1"] != ids["TAKE_PROFIT_2"]


def test_four_roles_yield_four_distinct_algo_client_ids() -> None:
    """Beh. 3b: ENTRY, STOP_LOSS, TAKE_PROFIT_1, TAKE_PROFIT_2 produce
    four distinct algo_client_ids for the same plan_hash.
    """
    from src.execution.order_ids import derive_algo_client_id

    case = _load_input()
    ids = {
        role: derive_algo_client_id(plan_hash=case["plan_hash"], role=role)
        for role in case["roles"]
    }
    assert len(set(ids.values())) == 4, (
        f"roles collided: {ids}"
    )


def test_client_and_algo_ids_for_same_role_do_not_collide() -> None:
    """Beh. 3c: for the same (plan_hash, role), client_order_id and
    algo_client_id are distinct identifiers.
    """
    from src.execution.order_ids import (
        derive_algo_client_id,
        derive_client_order_id,
    )

    case = _load_input()
    for role in case["roles"]:
        cid = derive_client_order_id(plan_hash=case["plan_hash"], role=role)
        aid = derive_algo_client_id(plan_hash=case["plan_hash"], role=role)
        assert cid != aid, (
            f"client_order_id and algo_client_id collided for role {role}: "
            f"{cid!r}"
        )


# --------------------------------------------------------------------------- #
# Beh. 4 — unknown role raises ValueError (never a fallback code).
# --------------------------------------------------------------------------- #


def test_unknown_role_raises_value_error() -> None:
    """Beh. 4: an unknown role string raises ValueError, never a fallback."""
    from src.execution.order_ids import derive_client_order_id

    case = _load_input()
    with pytest.raises(ValueError, match="role"):
        derive_client_order_id(plan_hash=case["plan_hash"], role="UNKNOWN")


def test_empty_role_raises_value_error() -> None:
    """Beh. 4b: an empty role string raises ValueError."""
    from src.execution.order_ids import derive_client_order_id

    case = _load_input()
    with pytest.raises(ValueError, match="role"):
        derive_client_order_id(plan_hash=case["plan_hash"], role="")


def test_non_string_role_raises_type_error() -> None:
    """Beh. 4c: a non-string role raises TypeError."""
    from src.execution.order_ids import derive_client_order_id

    case = _load_input()
    with pytest.raises(TypeError, match="role"):
        derive_client_order_id(plan_hash=case["plan_hash"], role=123)  # type: ignore[arg-type]


def test_non_string_plan_hash_raises_type_error() -> None:
    """Beh. 4d: a non-string plan_hash raises TypeError."""
    from src.execution.order_ids import derive_client_order_id

    with pytest.raises(TypeError, match="plan_hash"):
        derive_client_order_id(plan_hash=123, role="ENTRY")  # type: ignore[arg-type]


def test_empty_plan_hash_raises_value_error() -> None:
    """Beh. 4e: an empty plan_hash raises ValueError."""
    from src.execution.order_ids import derive_client_order_id

    with pytest.raises(ValueError, match="plan_hash"):
        derive_client_order_id(plan_hash="", role="ENTRY")


# --------------------------------------------------------------------------- #
# Beh. 5 — golden fixture vectors pin the derived IDs.
# --------------------------------------------------------------------------- #


def test_golden_fixture_client_order_ids_match_derivation() -> None:
    """Beh. 5a: the fixture's expected client_order_ids match the
    derivation output for all four roles.
    """
    from src.execution.order_ids import derive_client_order_id

    case = _load_input()
    expected = _load_expected()
    for role in case["roles"]:
        derived = derive_client_order_id(
            plan_hash=case["plan_hash"], role=role
        )
        assert derived == expected["client_order_ids"][role], (
            f"role {role}: derived={derived!r}, "
            f"expected={expected['client_order_ids'][role]!r}"
        )


def test_golden_fixture_algo_client_ids_match_derivation() -> None:
    """Beh. 5b: the fixture's expected algo_client_ids match the
    derivation output for all four roles.
    """
    from src.execution.order_ids import derive_algo_client_id

    case = _load_input()
    expected = _load_expected()
    for role in case["roles"]:
        derived = derive_algo_client_id(
            plan_hash=case["plan_hash"], role=role
        )
        assert derived == expected["algo_client_ids"][role], (
            f"role {role}: derived={derived!r}, "
            f"expected={expected['algo_client_ids'][role]!r}"
        )


# --------------------------------------------------------------------------- #
# Beh. 6 — different plan_hashes yield different IDs.
# --------------------------------------------------------------------------- #


def test_different_plan_hashes_yield_different_ids() -> None:
    """Beh. 6: changing the plan_hash changes every derived ID."""
    from src.execution.order_ids import derive_client_order_id

    base_hash = "1111111111111111111111111111111111111111111111111111111111111111"
    other_hash = "2222222222222222222222222222222222222222222222222222222222222222"
    assert base_hash != other_hash

    base_id = derive_client_order_id(plan_hash=base_hash, role="ENTRY")
    other_id = derive_client_order_id(plan_hash=other_hash, role="ENTRY")
    assert base_id != other_id


# --------------------------------------------------------------------------- #
# Beh. 7 — ROLE_CODES is a complete vocabulary (no missing or extra roles).
# --------------------------------------------------------------------------- #


def test_role_codes_covers_exactly_the_order_role_vocabulary() -> None:
    """Beh. 7: ROLE_CODES maps exactly the OrderRole enum values
    (ENTRY, STOP_LOSS, TAKE_PROFIT_1, TAKE_PROFIT_2) to distinct codes.
    """
    from src.domain.enums import OrderRole
    from src.execution.order_ids import ROLE_CODES

    assert set(ROLE_CODES.keys()) == {r.value for r in OrderRole}, (
        f"ROLE_CODES keys drift from OrderRole: "
        f"keys={set(ROLE_CODES.keys())}, "
        f"enum={set(r.value for r in OrderRole)}"
    )
    # Codes are distinct.
    assert len(set(ROLE_CODES.values())) == len(ROLE_CODES), (
        f"ROLE_CODES values collide: {ROLE_CODES}"
    )
