"""Per-plan exchange constraint snapshot (Phase 17, plan 06, EXEC-04, D-18, D-19, D-21).

Sizing must be reproducible and auditable from the exact exchange constraints used.
A `PlanConstraintSnapshot` records, for one trade plan, the symbol's tick and step
sizes, min and max quantity, min notional, the MARKET_LOT_SIZE and PERCENT_PRICE
filter values, the working type, margin type, leverage, the equity used and the
exchangeInfo capture time. It serializes to canonical JSON (sorted keys, Decimal as
text, no float) with a sha256 digest.

The digest is plan EVIDENCE only. It is never an input to `plan_hash`, so the
approval binding contract does not move (D-18).

Unknown is explicit. A value the system does not have is the string sentinel
`UNKNOWN` in the JSON (None in the dataclass), never zero and never an invented
default. Margin type, leverage and equity stay unknown until Phases 21-22, which
makes `live_inputs_status` INCOMPLETE; an INCOMPLETE snapshot is invalid for live
placement (D-19, D-21). Re-sizing a stale snapshot is Phase 19.

Purity: stdlib, Decimal, `src.domain` and `src.risk.types` only. No Binance SDK and
no `src.adapters` import; the caller maps adapter `SymbolFilters` fields onto the
primitive `ExchangeFilterExtras` (the Phase 19/24 wiring, and the tests).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from src.domain.canonical import canonical_bytes, sha256_hex
from src.domain.enums import LiveInputsStatus
from src.domain.registry import WORKING_TYPE_VALUES, ParameterSet
from src.risk.types import ConstraintSnapshot

#: Explicit sentinel for a value the system does not have (never zero, never a default).
UNKNOWN = "UNKNOWN"

#: Bumped when the JSON shape changes; `parse_snapshot_json` rejects any other value.
SNAPSHOT_SCHEMA_VERSION = 1

_TTL_KEY = "constraint_snapshot_ttl_seconds"

# Column widths of plan_constraint_snapshots (src/db/models.py).
_MAX_PLAN_ID_LEN = 128
_MAX_SYMBOL_LEN = 32
_MAX_WORKING_TYPE_LEN = 16
_MAX_MARGIN_TYPE_LEN = 16


# --------------------------------------------------------------------------- #
# Validation helpers
# --------------------------------------------------------------------------- #


def _require_text(value: object, name: str, max_len: int) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be str, got {type(value).__name__}")
    if value == "":
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > max_len:
        raise ValueError(f"{name} must be at most {max_len} characters, got {len(value)}")


def _require_positive_decimal(value: object, name: str) -> None:
    """Decimal only (a float raises TypeError), finite and > 0."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite, got {value}")
    if value <= Decimal(0):
        raise ValueError(f"{name} must be > 0, got {value}")


def _require_optional_positive_decimal(value: object, name: str) -> None:
    if value is not None:
        _require_positive_decimal(value, name)


def _require_optional_int(value: object, name: str, *, minimum: int) -> None:
    """int only (bool and float raise TypeError), >= `minimum`; None passes."""
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be int, got {type(value).__name__}")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")


def _require_utc_aware(value: object, name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        raise ValueError(f"{name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC, got offset {value.utcoffset()}")


# --------------------------------------------------------------------------- #
# Value objects
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ExchangeFilterExtras:
    """MARKET_LOT_SIZE and PERCENT_PRICE values, as the adapter parsed them.

    Primitive mirror of the six optional trailing `SymbolFilters` fields, so this
    module never imports the adapter. None means the exchange did not publish the
    filter (it becomes `UNKNOWN` in the snapshot JSON).
    """

    market_lot_min_quantity: Decimal | None = None
    market_lot_max_quantity: Decimal | None = None
    market_lot_step_size: Decimal | None = None
    percent_price_multiplier_up: Decimal | None = None
    percent_price_multiplier_down: Decimal | None = None
    percent_price_multiplier_decimals: int | None = None

    def __post_init__(self) -> None:
        _require_optional_positive_decimal(self.market_lot_min_quantity, "market_lot_min_quantity")
        _require_optional_positive_decimal(self.market_lot_max_quantity, "market_lot_max_quantity")
        _require_optional_positive_decimal(self.market_lot_step_size, "market_lot_step_size")
        _require_optional_positive_decimal(
            self.percent_price_multiplier_up, "percent_price_multiplier_up"
        )
        _require_optional_positive_decimal(
            self.percent_price_multiplier_down, "percent_price_multiplier_down"
        )
        _require_optional_int(
            self.percent_price_multiplier_decimals, "percent_price_multiplier_decimals", minimum=0
        )


@dataclass(frozen=True)
class PlanConstraintSnapshot:
    """Exact exchange constraints used to size one trade plan.

    `constraints_observed_at_utc` is the exchangeInfo capture time (the instant the
    staleness predicate measures from); `captured_at_utc` is when this snapshot was
    recorded. None for any optional field means unknown (`UNKNOWN` in the JSON).
    """

    trade_plan_id: str
    symbol: str
    price_tick_size: Decimal
    quantity_step_size: Decimal
    min_quantity: Decimal
    max_quantity: Decimal | None
    min_notional: Decimal
    market_lot_min_quantity: Decimal | None
    market_lot_max_quantity: Decimal | None
    market_lot_step_size: Decimal | None
    percent_price_multiplier_up: Decimal | None
    percent_price_multiplier_down: Decimal | None
    percent_price_multiplier_decimals: int | None
    working_type: str
    margin_type: str | None
    leverage: int | None
    equity_used: Decimal | None
    constraints_observed_at_utc: datetime
    captured_at_utc: datetime

    def __post_init__(self) -> None:
        _require_text(self.trade_plan_id, "trade_plan_id", _MAX_PLAN_ID_LEN)
        _require_text(self.symbol, "symbol", _MAX_SYMBOL_LEN)
        for name in ("price_tick_size", "quantity_step_size", "min_quantity", "min_notional"):
            _require_positive_decimal(getattr(self, name), name)
        for name in (
            "max_quantity",
            "market_lot_min_quantity",
            "market_lot_max_quantity",
            "market_lot_step_size",
            "percent_price_multiplier_up",
            "percent_price_multiplier_down",
            "equity_used",
        ):
            _require_optional_positive_decimal(getattr(self, name), name)
        _require_optional_int(
            self.percent_price_multiplier_decimals, "percent_price_multiplier_decimals", minimum=0
        )
        _require_optional_int(self.leverage, "leverage", minimum=1)
        _require_text(self.working_type, "working_type", _MAX_WORKING_TYPE_LEN)
        if self.working_type not in WORKING_TYPE_VALUES:
            raise ValueError(
                f"working_type must be one of {sorted(WORKING_TYPE_VALUES)}, "
                f"got {self.working_type!r}"
            )
        if self.margin_type is not None:
            _require_text(self.margin_type, "margin_type", _MAX_MARGIN_TYPE_LEN)
            if self.margin_type == UNKNOWN:
                raise ValueError("margin_type must be None (not the UNKNOWN sentinel) when unknown")
        _require_utc_aware(self.constraints_observed_at_utc, "constraints_observed_at_utc")
        _require_utc_aware(self.captured_at_utc, "captured_at_utc")

    @property
    def live_inputs_status(self) -> LiveInputsStatus:
        """COMPLETE only when margin type, leverage, equity and every filter value are known."""
        unknowns = (
            self.margin_type,
            self.leverage,
            self.equity_used,
            self.max_quantity,
            self.market_lot_min_quantity,
            self.market_lot_max_quantity,
            self.market_lot_step_size,
            self.percent_price_multiplier_up,
            self.percent_price_multiplier_down,
            self.percent_price_multiplier_decimals,
        )
        if any(value is None for value in unknowns):
            return LiveInputsStatus.INCOMPLETE
        return LiveInputsStatus.COMPLETE


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #


def build_plan_constraint_snapshot(
    trade_plan_id: str,
    constraints: ConstraintSnapshot,
    extras: ExchangeFilterExtras,
    max_quantity: Decimal | None,
    working_type: str,
    *,
    margin_type: str | None = None,
    leverage: int | None = None,
    equity_used: Decimal | None = None,
    captured_at_utc: datetime,
) -> PlanConstraintSnapshot:
    """Assemble the per-plan snapshot from the risk constraints and the extra filters.

    `constraints.metadata_observed_at_utc` becomes `constraints_observed_at_utc`.
    Margin type, leverage and equity default to None (UNKNOWN) until Phases 21-22
    supply them; any None makes the snapshot INCOMPLETE and invalid for live.
    """
    if not isinstance(constraints, ConstraintSnapshot):
        raise TypeError(f"constraints must be ConstraintSnapshot, got {type(constraints).__name__}")
    if not isinstance(extras, ExchangeFilterExtras):
        raise TypeError(f"extras must be ExchangeFilterExtras, got {type(extras).__name__}")
    return PlanConstraintSnapshot(
        trade_plan_id=trade_plan_id,
        symbol=constraints.symbol,
        price_tick_size=constraints.price_tick_size,
        quantity_step_size=constraints.quantity_step_size,
        min_quantity=constraints.min_quantity,
        max_quantity=max_quantity,
        min_notional=constraints.min_notional,
        market_lot_min_quantity=extras.market_lot_min_quantity,
        market_lot_max_quantity=extras.market_lot_max_quantity,
        market_lot_step_size=extras.market_lot_step_size,
        percent_price_multiplier_up=extras.percent_price_multiplier_up,
        percent_price_multiplier_down=extras.percent_price_multiplier_down,
        percent_price_multiplier_decimals=extras.percent_price_multiplier_decimals,
        working_type=working_type,
        margin_type=margin_type,
        leverage=leverage,
        equity_used=equity_used,
        constraints_observed_at_utc=constraints.metadata_observed_at_utc,
        captured_at_utc=captured_at_utc,
    )


# --------------------------------------------------------------------------- #
# Canonical JSON, hash, parse
# --------------------------------------------------------------------------- #

_VERSION_KEY = "snapshot_schema_version"
_FIELD_NAMES = tuple(f.name for f in fields(PlanConstraintSnapshot))
_REQUIRED_DECIMALS = ("price_tick_size", "quantity_step_size", "min_quantity", "min_notional")
_OPTIONAL_DECIMALS = (
    "max_quantity",
    "market_lot_min_quantity",
    "market_lot_max_quantity",
    "market_lot_step_size",
    "percent_price_multiplier_up",
    "percent_price_multiplier_down",
    "equity_used",
)
_OPTIONAL_INTS = ("percent_price_multiplier_decimals", "leverage")
_DATETIMES = ("constraints_observed_at_utc", "captured_at_utc")


def _payload(snapshot: PlanConstraintSnapshot) -> dict[str, Any]:
    """The dict that is hashed and serialized: None becomes the UNKNOWN sentinel."""
    doc: dict[str, Any] = {}
    for name in _FIELD_NAMES:
        value = getattr(snapshot, name)
        doc[name] = UNKNOWN if value is None else value
    doc[_VERSION_KEY] = SNAPSHOT_SCHEMA_VERSION
    return doc


def canonical_json(snapshot: PlanConstraintSnapshot) -> str:
    """Canonical JSON text: sorted keys, compact, Decimal as text, no float.

    Byte-identical for equal snapshots (it is `canonical_bytes` of the payload).
    """
    return canonical_bytes(_payload(snapshot)).decode("ascii")


def snapshot_sha256(snapshot: PlanConstraintSnapshot) -> str:
    """sha256 hex of the canonical JSON bytes. Evidence only, never part of plan_hash."""
    return sha256_hex(_payload(snapshot))


def _reject_float(literal: str) -> Any:
    raise ValueError(f"float literal {literal!r} in snapshot JSON (Decimal text required)")


def _reject_constant(literal: str) -> Any:
    raise ValueError(f"non-finite constant {literal!r} in snapshot JSON")


def _decode_decimal(name: str, raw: object, *, optional: bool) -> Decimal | None:
    if raw == UNKNOWN and optional:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"{name} must be Decimal text, got {type(raw).__name__}")
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"{name} is not Decimal text: {raw!r}") from exc


def _decode_int(name: str, raw: object) -> int | None:
    if raw == UNKNOWN:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"{name} must be an integer or {UNKNOWN}, got {type(raw).__name__}")
    return raw


def _decode_datetime(name: str, raw: object) -> datetime:
    if not isinstance(raw, str):
        raise ValueError(f"{name} must be ISO-8601 text, got {type(raw).__name__}")
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{name} is not an ISO-8601 datetime: {raw!r}") from exc


def parse_snapshot_json(text: str) -> PlanConstraintSnapshot:
    """Rebuild a snapshot from its canonical JSON (UNKNOWN back to None).

    Strict: unknown or missing keys, JSON floats or constants, non-text Decimals,
    a naive or non-UTC datetime and a foreign schema version all raise ValueError.
    """
    try:
        doc = json.loads(text, parse_float=_reject_float, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise ValueError(f"snapshot JSON is not valid JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError(f"snapshot JSON must be an object, got {type(doc).__name__}")
    expected = {*_FIELD_NAMES, _VERSION_KEY}
    if set(doc) != expected:
        extra = sorted(set(doc) - expected)
        missing = sorted(expected - set(doc))
        raise ValueError(f"snapshot JSON keys differ: unknown={extra} missing={missing}")
    version = doc[_VERSION_KEY]
    if isinstance(version, bool) or version != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported snapshot schema version {version!r} (expected {SNAPSHOT_SCHEMA_VERSION})"
        )
    values: dict[str, Any] = {}
    for name in _FIELD_NAMES:
        raw = doc[name]
        if name in _REQUIRED_DECIMALS:
            values[name] = _decode_decimal(name, raw, optional=False)
        elif name in _OPTIONAL_DECIMALS:
            values[name] = _decode_decimal(name, raw, optional=True)
        elif name in _OPTIONAL_INTS:
            values[name] = _decode_int(name, raw)
        elif name in _DATETIMES:
            values[name] = _decode_datetime(name, raw)
        elif name == "margin_type":
            values[name] = None if raw == UNKNOWN else raw
        else:
            values[name] = raw
    try:
        return PlanConstraintSnapshot(**values)
    except TypeError as exc:
        raise ValueError(f"snapshot JSON field has the wrong type: {exc}") from exc


# --------------------------------------------------------------------------- #
# Live validity
# --------------------------------------------------------------------------- #


def snapshot_is_valid_for_live(
    snapshot: PlanConstraintSnapshot,
    *,
    now_utc: datetime,
    ttl: timedelta,
) -> bool:
    """True only for a COMPLETE snapshot whose exchange capture is fresh.

    Reuses the placement gate's stale predicate (`src/execution/gates.py`): stale
    when `age > ttl` or `age < 0` (a future-dated capture is clock skew or corrupt
    upstream metadata and fails closed). Age is measured from the exchangeInfo
    capture time, so exactly `ttl` is still valid. An INCOMPLETE snapshot is never
    valid for live (D-19).
    """
    _require_utc_aware(now_utc, "now_utc")
    if not isinstance(ttl, timedelta):
        raise TypeError(f"ttl must be timedelta, got {type(ttl).__name__}")
    if ttl < timedelta(0):
        raise ValueError(f"ttl must be >= 0, got {ttl}")
    if snapshot.live_inputs_status is not LiveInputsStatus.COMPLETE:
        return False
    age = now_utc - snapshot.constraints_observed_at_utc
    return not (age > ttl or age < timedelta(0))


def ttl_from_parameter_set(parameter_set: ParameterSet) -> timedelta:
    """The snapshot TTL from `constraint_snapshot_ttl_seconds`, never a hard-coded number.

    A missing, non-integer or non-positive value raises ValueError (fail closed).
    """
    try:
        raw = parameter_set.params[_TTL_KEY]
    except KeyError as exc:
        raise ValueError(f"parameter set has no {_TTL_KEY}") from exc
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ValueError(f"{_TTL_KEY} must be a positive integer, got {raw!r}")
    return timedelta(seconds=raw)


__all__ = [
    "SNAPSHOT_SCHEMA_VERSION",
    "UNKNOWN",
    "ExchangeFilterExtras",
    "PlanConstraintSnapshot",
    "build_plan_constraint_snapshot",
    "canonical_json",
    "parse_snapshot_json",
    "snapshot_is_valid_for_live",
    "snapshot_sha256",
    "ttl_from_parameter_set",
]
