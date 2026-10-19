"""Deterministic client/algo order identifier derivation (Phase 8, plan 08-03).

Per D-04: a retry, restart, or replay of an approved plan reuses the same
identifier instead of minting a new one. The derivation is a pure function of
`(plan_hash, role)` over stdlib `hashlib` only.

What the ids are for, and what they are NOT (Phase 17, D-13, F-951, research C18):
the ids are deterministic so that a probe by client id can find an order that was
sent but whose response was lost, and so that every restart derives the same id.
They are NOT an exchange-side duplicate guard. Binance treats `newClientOrderId` and
`clientAlgoId` as unique only among OPEN orders: once the earlier order is FILLED or
CANCELED the id is free again and the exchange accepts a second order with it.
Duplicate-entry protection is therefore the persisted execution intent written by
`src/execution/manager.py` before `place_entry` (see `intent_store.py`), never the
exchange.

Pinned ID shape (re-verified against the installed Binance SDK during
this plan; the SDK exposes response models only — request validation
lives server-side, and the documented client-order-ID rule is
"<= 36 chars, ASCII letters/digits/hyphen/underscore"):

  - client_order_id:  "x-" (2) + plan_hash[:32] (32) + role_code (2) = 36
  - algo_client_id:   "xa-" (3) + plan_hash[:31] (31) + role_code (2) = 36
  - close_order_id:   "xc-" (3) + plan_hash[:29] (29) + attempt_no (4 digits) = 36
                      (Phase 19, plan 19-12: the automatic reduce-only MARKET close; one id
                      per attempt, so ROLE_CODES and OrderRole stay untouched)

The charset is a strict subset of the Binance-allowed set
(`0123456789abcdef-`), so the derivation is always accepted by the
exchange validator. The plan_hash slice is the first N hex chars of the
canonical 64-char SHA-256 plan hash — deterministic across processes
and Python versions.

The module is dependency-free: stdlib + `src/domain/enums.py` only.
No Telegram, no Binance SDK, no SQLAlchemy, no Pydantic, no Polars.
"""

from __future__ import annotations

from src.domain.enums import OrderRole

# --------------------------------------------------------------------------- #
# Canonical role-to-code table (D-04).
#
# This is the ONLY place role-code literals appear. The sweeper (08-04)
# and fixtures import from here. Unknown roles raise ValueError — there
# is no fallback code.
# --------------------------------------------------------------------------- #

ROLE_CODES: dict[str, str] = {
    OrderRole.ENTRY.value: "EN",
    OrderRole.STOP_LOSS.value: "SL",
    OrderRole.TAKE_PROFIT_1.value: "T1",
    OrderRole.TAKE_PROFIT_2.value: "T2",
}

# Pinned ID length (Binance client-order-ID max).
_ID_LENGTH = 36

# Pinned prefix lengths.
_CLIENT_PREFIX = "x-"
_CLIENT_PLAN_SLICE_LEN = 32
_ALGO_PREFIX = "xa-"
_ALGO_PLAN_SLICE_LEN = 31
_CLOSE_PREFIX = "xc-"
_CLOSE_PLAN_SLICE_LEN = 29
_CLOSE_MAX_ATTEMPT_NO = 9999


def _require_plan_hash(plan_hash: object) -> str:
    """Validate plan_hash is a 64-char lowercase hex string (D-12 boundary)."""
    if not isinstance(plan_hash, str):
        raise TypeError(f"plan_hash must be str, got {type(plan_hash).__name__}")
    if plan_hash == "":
        raise ValueError("plan_hash must be a non-empty string")
    if len(plan_hash) != 64 or any(c not in "0123456789abcdef" for c in plan_hash):
        raise ValueError(
            "plan_hash must be a 64-char lowercase hex string "
            f"(SHA-256 identity), got {plan_hash!r}"
        )
    return plan_hash


def _require_role(role: object) -> str:
    """Validate role is a known OrderRole value (D-04 vocabulary)."""
    if not isinstance(role, str):
        raise TypeError(f"role must be str, got {type(role).__name__}")
    if role == "":
        raise ValueError("role must be a non-empty string")
    if role not in ROLE_CODES:
        raise ValueError(
            f"role {role!r} is not in the canonical ROLE_CODES vocabulary; "
            f"known roles: {sorted(ROLE_CODES.keys())}"
        )
    return role


def derive_client_order_id(*, plan_hash: str, role: str) -> str:
    """Return the deterministic Binance client_order_id for a plan leg.

    Per D-04: the same `(plan_hash, role)` always yields the same
    client_order_id across processes, restarts, and replays, so a probe
    by client id can find the order. Binance only rejects a duplicate
    while the earlier order is still OPEN, so this identifier is NOT a
    duplicate-entry guard; the persisted execution intent is (D-13).

    Args:
        plan_hash: The 64-char SHA-256 hex digest of the parent
            TradePlan (the canonical plan identity).
        role: One of the OrderRole values (ENTRY, STOP_LOSS,
            TAKE_PROFIT_1, TAKE_PROFIT_2). Unknown roles raise
            ValueError.

    Returns:
        A 36-char ASCII string of the form
        ``x-<plan_hash[:32]><role_code>``.

    Raises:
        TypeError: plan_hash or role is not a string.
        ValueError: plan_hash is empty, role is empty, or role is not
            in the canonical ROLE_CODES vocabulary.
    """
    validated_hash = _require_plan_hash(plan_hash)
    validated_role = _require_role(role)
    role_code = ROLE_CODES[validated_role]
    return _CLIENT_PREFIX + validated_hash[:_CLIENT_PLAN_SLICE_LEN] + role_code


def derive_algo_client_id(*, plan_hash: str, role: str) -> str:
    """Return the deterministic Binance algo_client_id for a plan leg.

    Per D-04: the same `(plan_hash, role)` always yields the same
    algo_client_id across processes, restarts, and replays. Used for
    CONDITIONAL algo orders (STOP_MARKET / TAKE_PROFIT_MARKET) where
    Binance uses a separate identifier namespace.

    Args:
        plan_hash: The 64-char SHA-256 hex digest of the parent
            TradePlan.
        role: One of the OrderRole values (ENTRY, STOP_LOSS,
            TAKE_PROFIT_1, TAKE_PROFIT_2). Unknown roles raise
            ValueError.

    Returns:
        A 36-char ASCII string of the form
        ``xa-<plan_hash[:31]><role_code>``.

    Raises:
        TypeError: plan_hash or role is not a string.
        ValueError: plan_hash is empty, role is empty, or role is not
            in the canonical ROLE_CODES vocabulary.
    """
    validated_hash = _require_plan_hash(plan_hash)
    validated_role = _require_role(role)
    role_code = ROLE_CODES[validated_role]
    return _ALGO_PREFIX + validated_hash[:_ALGO_PLAN_SLICE_LEN] + role_code


def derive_close_order_id(*, plan_hash: str, attempt_no: int) -> str:
    """Return the deterministic client_order_id of one emergency-close attempt.

    Plan 19-12 (D-15): every part of the automatic reduce-only MARKET close is sent under its
    own id, ``xc-<plan_hash[:29]><attempt_no:04d>`` (36 characters, the charset of the other
    derived ids). The same ``(plan_hash, attempt_no)`` always yields the same id, so a probe by
    client id finds an attempt whose answer was lost, also after a restart. An attempt number is
    never reused for a second send. Like the other ids this is NOT an exchange-side duplicate
    guard (Binance treats the id as unique among OPEN orders only): the guard is the
    query-before-resend rule of the closer.

    Raises:
        TypeError: plan_hash is not a string, or attempt_no is not an int (a bool is refused).
        ValueError: plan_hash is not a 64-char lowercase hex string, or attempt_no is not in
            1..9999.
    """
    validated_hash = _require_plan_hash(plan_hash)
    if isinstance(attempt_no, bool) or not isinstance(attempt_no, int):
        raise TypeError(f"attempt_no must be int, got {type(attempt_no).__name__}")
    if not 1 <= attempt_no <= _CLOSE_MAX_ATTEMPT_NO:
        raise ValueError(f"attempt_no must be in 1..{_CLOSE_MAX_ATTEMPT_NO}, got {attempt_no}")
    return _CLOSE_PREFIX + validated_hash[:_CLOSE_PLAN_SLICE_LEN] + f"{attempt_no:04d}"


__all__ = [
    "ROLE_CODES",
    "derive_client_order_id",
    "derive_algo_client_id",
    "derive_close_order_id",
]
