"""Paper record assembly — three-way attribution journaling (Phase 7, plan 07-03).

Per D-03: every paper record carries the canonical identity tuple
(strategyVersion + parameterSetId + parameterSetHash + experiment linkage
+ SignalId/plan hash + epoch_id) plus the full timestamp lineage
(signal/approve(simulated)/order(fill-simulated)/fill). Attribution
splits three ways: system (engine emitted), user-executed-sim (SIMULATE
fill with approval-delay modeling), and opportunity (skipped/expired
plans retained with reason codes — never dropped).

The module imports only stdlib + sibling modules (per the plan's purity
contract for this slice). The ORM layer lives behind `src/db/mappers.py`
and is NOT imported here — the assembler produces frozen `PaperRecord`
dataclass instances that the journal layer maps onto existing ORM rows
via the thin-mapper pattern (D-02 single-Base ORM discipline).

The Parquet file-extract pipeline mirroring the journal is explicitly
deferred to Phase 10 (which owns journal analytics depth). Every row
already carries `epoch_id` plus the full canonical identity so deferred
extraction loses nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.domain.canonical import sha256_hex

from .attribution import APPROVAL_DELAY_LAG_SECONDS, AttributionKind


# --------------------------------------------------------------------------- #
# Validation helpers — local copies (D-12 fail-closed).
# --------------------------------------------------------------------------- #


def _require_non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_utc_aware(value: datetime | None, field_name: str) -> None:
    if value is None:
        return
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(
            f"{field_name} must be UTC, got offset {value.utcoffset()}"
        )


# --------------------------------------------------------------------------- #
# PaperRecord — frozen dataclass carrying the canonical identity tuple,
# timestamp lineage, and attribution kind.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PaperRecord:
    """A single attributed paper record (D-03).

    Carries:
      - `attribution`: the three-way attribution kind (system,
        user-executed-sim, opportunity).
      - `epoch_id`: the caller-supplied stream epoch identifier
        (from `src/paper/freeze.py`). Every row carries it so future
        Parquet extraction partitioned by epoch is lossless.
      - Identity tuple: `strategy_id`, `strategy_version`,
        `parameter_set_id`, `parameter_set_hash`, `experiment_id`,
        `symbol`, `signal_id`, `plan_hash`. `signal_id` and `plan_hash`
        are None for NO_TRADE rows (no signal was emitted).
      - Timestamp lineage: `signal_detected_at_utc`,
        `approval_acted_at_utc`, `order_submitted_at_utc`,
        `fill_time_utc`. Each is None when the corresponding
        transition never happened (D-11).
      - `reason_code`: the rejection/skip/expire reason code for
        opportunity and NO_TRADE rows; empty string for system and
        user-executed-sim rows that passed the chain.
    """

    attribution: AttributionKind
    epoch_id: str
    strategy_id: str
    strategy_version: str
    parameter_set_id: str
    parameter_set_hash: str
    experiment_id: str
    symbol: str
    signal_id: str | None
    plan_hash: str | None
    reason_code: str
    signal_detected_at_utc: datetime | None
    approval_acted_at_utc: datetime | None
    order_submitted_at_utc: datetime | None
    fill_time_utc: datetime | None

    def __post_init__(self) -> None:
        # D-12: identity completeness — empty fields rejected loudly.
        for fname in (
            "epoch_id",
            "strategy_id",
            "strategy_version",
            "parameter_set_id",
            "parameter_set_hash",
            "experiment_id",
            "symbol",
        ):
            _require_non_empty(getattr(self, fname), fname)
        # D-12: UTC-aware datetimes only.
        _require_utc_aware(self.signal_detected_at_utc, "signal_detected_at_utc")
        _require_utc_aware(self.approval_acted_at_utc, "approval_acted_at_utc")
        _require_utc_aware(self.order_submitted_at_utc, "order_submitted_at_utc")
        _require_utc_aware(self.fill_time_utc, "fill_time_utc")


# --------------------------------------------------------------------------- #
# Helpers — parse fixture dicts into the canonical identity tuple.
# --------------------------------------------------------------------------- #


def _parse_utc(raw: str | None) -> datetime | None:
    """Parse an ISO-8601 string into a UTC-aware datetime, or None."""
    if raw is None:
        return None
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise ValueError(f"naive datetime in fixture: {raw!r}")
    return value.astimezone(tz=__import__("datetime").UTC)


def _identity_from_signal(signal: dict[str, Any]) -> dict[str, str]:
    """Extract the canonical identity tuple from a signal dict."""
    return {
        "strategy_id": signal["strategy_id"],
        "strategy_version": signal["strategy_version"],
        "parameter_set_id": signal["parameter_set_id"],
        "parameter_set_hash": signal["parameter_set_hash"],
        "experiment_id": signal["experiment_id"],
        "symbol": signal["symbol"],
        "signal_id": signal["signal"]["signal_id"],
        "plan_hash": signal["trade_plan"]["plan_hash"],
    }


def _identity_from_no_trade(case: dict[str, Any]) -> dict[str, str]:
    """Extract the canonical identity tuple from a NO_TRADE case dict."""
    return {
        "strategy_id": case["strategy_id"],
        "strategy_version": case["strategy_version"],
        "parameter_set_id": case["parameter_set_id"],
        "parameter_set_hash": case["parameter_set_hash"],
        "experiment_id": case["experiment_id"],
        "symbol": case["symbol"],
    }


# --------------------------------------------------------------------------- #
# Public entry point — assemble_paper_record.
# --------------------------------------------------------------------------- #


def assemble_paper_record(
    *,
    epoch_id: str,
    signal: dict[str, Any],
    trade_plan: dict[str, Any],
    approval: dict[str, Any] | None,
    order: dict[str, Any] | None,
    fill: dict[str, Any] | None,
    skip_reason: str | None = None,
    expired_at_utc: str | None = None,
) -> list[PaperRecord]:
    """Assemble a paper record (or pair) from a loop outcome.

    Per D-03: the assembler maps a loop outcome onto one or two
    `PaperRecord` instances:

      - Filled in simulation (approval + order + fill all present):
        returns `[system_row, user_executed_sim_row]`. The
        user-executed-sim row's `approval_acted_at_utc` equals
        `signal.detected_at_utc + APPROVAL_DELAY_LAG_SECONDS`.

      - Skipped (skip_reason set, no approval/order/fill):
        returns `[system_row, opportunity_row]` with the skip reason
        code on the opportunity row.

      - Expired (expired_at_utc set, no approval/order/fill):
        returns `[system_row, opportunity_row]` with reason code
        `EXPIRED` on the opportunity row.

    The caller supplies `epoch_id` (from `src/paper/freeze.py`) so
    every row carries the stream epoch identifier for future Parquet
    extraction partitioned by epoch.

    The function is a pure function of its inputs — no I/O, no clock
    reads, no randomness. The ORM layer maps these records onto
    existing seven-entity rows via `src/db/mappers.py` (D-02 single-Base
    ORM discipline, no new tables).
    """
    # Build the identity tuple from the signal + trade_plan.
    identity = {
        "strategy_id": signal["strategy_id"],
        "strategy_version": signal["strategy_version"],
        "parameter_set_id": signal["parameter_set_id"],
        "parameter_set_hash": signal["parameter_set_hash"],
        "experiment_id": signal["experiment_id"],
        "symbol": signal["symbol"],
        "signal_id": signal["signal_id"],
        "plan_hash": trade_plan["plan_hash"],
    }

    signal_detected_at_utc = _parse_utc(signal["detected_at_utc"])
    assert signal_detected_at_utc is not None  # _parse_utc returns None only for None input

    # Case 1: filled in simulation — system + user-executed-sim.
    if approval is not None and order is not None and fill is not None:
        # The simulated approval acted_at_utc equals signal time + lag.
        simulated_acted_at_utc = signal_detected_at_utc + timedelta(
            seconds=APPROVAL_DELAY_LAG_SECONDS
        )
        order_submitted_at_utc = _parse_utc(order["submitted_at_utc"])
        fill_time_utc = _parse_utc(fill["fill_time_utc"])

        system_row = PaperRecord(
            attribution=AttributionKind.SYSTEM,
            epoch_id=epoch_id,
            strategy_id=identity["strategy_id"],
            strategy_version=identity["strategy_version"],
            parameter_set_id=identity["parameter_set_id"],
            parameter_set_hash=identity["parameter_set_hash"],
            experiment_id=identity["experiment_id"],
            symbol=identity["symbol"],
            signal_id=identity["signal_id"],
            plan_hash=identity["plan_hash"],
            reason_code="",
            signal_detected_at_utc=signal_detected_at_utc,
            approval_acted_at_utc=None,
            order_submitted_at_utc=None,
            fill_time_utc=None,
        )
        user_executed_sim_row = PaperRecord(
            attribution=AttributionKind.USER_EXECUTED_SIM,
            epoch_id=epoch_id,
            strategy_id=identity["strategy_id"],
            strategy_version=identity["strategy_version"],
            parameter_set_id=identity["parameter_set_id"],
            parameter_set_hash=identity["parameter_set_hash"],
            experiment_id=identity["experiment_id"],
            symbol=identity["symbol"],
            signal_id=identity["signal_id"],
            plan_hash=identity["plan_hash"],
            reason_code="",
            signal_detected_at_utc=signal_detected_at_utc,
            approval_acted_at_utc=simulated_acted_at_utc,
            order_submitted_at_utc=order_submitted_at_utc,
            fill_time_utc=fill_time_utc,
        )
        return [system_row, user_executed_sim_row]

    # Case 2: skipped — system + opportunity with skip reason.
    if skip_reason is not None:
        system_row = PaperRecord(
            attribution=AttributionKind.SYSTEM,
            epoch_id=epoch_id,
            strategy_id=identity["strategy_id"],
            strategy_version=identity["strategy_version"],
            parameter_set_id=identity["parameter_set_id"],
            parameter_set_hash=identity["parameter_set_hash"],
            experiment_id=identity["experiment_id"],
            symbol=identity["symbol"],
            signal_id=identity["signal_id"],
            plan_hash=identity["plan_hash"],
            reason_code="",
            signal_detected_at_utc=signal_detected_at_utc,
            approval_acted_at_utc=None,
            order_submitted_at_utc=None,
            fill_time_utc=None,
        )
        opportunity_row = PaperRecord(
            attribution=AttributionKind.OPPORTUNITY,
            epoch_id=epoch_id,
            strategy_id=identity["strategy_id"],
            strategy_version=identity["strategy_version"],
            parameter_set_id=identity["parameter_set_id"],
            parameter_set_hash=identity["parameter_set_hash"],
            experiment_id=identity["experiment_id"],
            symbol=identity["symbol"],
            signal_id=identity["signal_id"],
            plan_hash=identity["plan_hash"],
            reason_code=skip_reason,
            signal_detected_at_utc=signal_detected_at_utc,
            approval_acted_at_utc=None,
            order_submitted_at_utc=None,
            fill_time_utc=None,
        )
        return [system_row, opportunity_row]

    # Case 3: expired — system + opportunity with EXPIRED.
    if expired_at_utc is not None:
        system_row = PaperRecord(
            attribution=AttributionKind.SYSTEM,
            epoch_id=epoch_id,
            strategy_id=identity["strategy_id"],
            strategy_version=identity["strategy_version"],
            parameter_set_id=identity["parameter_set_id"],
            parameter_set_hash=identity["parameter_set_hash"],
            experiment_id=identity["experiment_id"],
            symbol=identity["symbol"],
            signal_id=identity["signal_id"],
            plan_hash=identity["plan_hash"],
            reason_code="",
            signal_detected_at_utc=signal_detected_at_utc,
            approval_acted_at_utc=None,
            order_submitted_at_utc=None,
            fill_time_utc=None,
        )
        opportunity_row = PaperRecord(
            attribution=AttributionKind.OPPORTUNITY,
            epoch_id=epoch_id,
            strategy_id=identity["strategy_id"],
            strategy_version=identity["strategy_version"],
            parameter_set_id=identity["parameter_set_id"],
            parameter_set_hash=identity["parameter_set_hash"],
            experiment_id=identity["experiment_id"],
            symbol=identity["symbol"],
            signal_id=identity["signal_id"],
            plan_hash=identity["plan_hash"],
            reason_code="EXPIRED",
            signal_detected_at_utc=signal_detected_at_utc,
            approval_acted_at_utc=None,
            order_submitted_at_utc=None,
            fill_time_utc=None,
        )
        return [system_row, opportunity_row]

    # No valid case matched — fail closed.
    raise ValueError(
        "assemble_paper_record requires either (approval + order + fill) "
        "for filled simulation, skip_reason for skipped, or expired_at_utc "
        "for expired"
    )


# --------------------------------------------------------------------------- #
# Public entry point — assemble_no_trade_record.
# --------------------------------------------------------------------------- #


def assemble_no_trade_record(
    *,
    epoch_id: str,
    strategy_id: str,
    strategy_version: str,
    parameter_set_id: str,
    parameter_set_hash: str,
    experiment_id: str,
    symbol: str,
    reason_code: str,
) -> PaperRecord:
    """Assemble a NO_TRADE paper record.

    Per D-03: a NO_TRADE outcome (no signal emitted) yields a single
    `system` row with the reason code and no SignalId/plan hash. The
    row carries the epoch_id and the canonical identity tuple (minus
    SignalId/plan hash which don't exist for a NO_TRADE).
    """
    return PaperRecord(
        attribution=AttributionKind.SYSTEM,
        epoch_id=epoch_id,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        parameter_set_id=parameter_set_id,
        parameter_set_hash=parameter_set_hash,
        experiment_id=experiment_id,
        symbol=symbol,
        signal_id=None,
        plan_hash=None,
        reason_code=reason_code,
        signal_detected_at_utc=None,
        approval_acted_at_utc=None,
        order_submitted_at_utc=None,
        fill_time_utc=None,
    )


# --------------------------------------------------------------------------- #
# Public entry point — paper_records_digest.
# --------------------------------------------------------------------------- #


def paper_records_digest(records: list[PaperRecord]) -> str:
    """Compute the canonical digest of a list of PaperRecord instances.

    Per D-03: the assembled rows form a canonical-JSON-safe digest
    that must equal the pinned expected digest. Any change to the
    assembly contract (field order, serialization, identity tuple)
    fails this check.

    The digest is computed over a sorted list of canonical-JSON-safe
    dicts, one per record. The sort key is `(attribution, signal_id,
    plan_hash)` so the digest is stable across Python dict ordering.
    """
    payload: list[dict[str, Any]] = []
    for record in records:
        payload.append(
            {
                "attribution": record.attribution.value,
                "epoch_id": record.epoch_id,
                "strategy_id": record.strategy_id,
                "strategy_version": record.strategy_version,
                "parameter_set_id": record.parameter_set_id,
                "parameter_set_hash": record.parameter_set_hash,
                "experiment_id": record.experiment_id,
                "symbol": record.symbol,
                "signal_id": record.signal_id,
                "plan_hash": record.plan_hash,
                "reason_code": record.reason_code,
                "signal_detected_at_utc": (
                    record.signal_detected_at_utc.isoformat()
                    if record.signal_detected_at_utc is not None
                    else None
                ),
                "approval_acted_at_utc": (
                    record.approval_acted_at_utc.isoformat()
                    if record.approval_acted_at_utc is not None
                    else None
                ),
                "order_submitted_at_utc": (
                    record.order_submitted_at_utc.isoformat()
                    if record.order_submitted_at_utc is not None
                    else None
                ),
                "fill_time_utc": (
                    record.fill_time_utc.isoformat()
                    if record.fill_time_utc is not None
                    else None
                ),
            }
        )
    # Sort by (attribution, signal_id, plan_hash) for stable ordering.
    payload.sort(
        key=lambda r: (
            r["attribution"],
            r["signal_id"] or "",
            r["plan_hash"] or "",
        )
    )
    return sha256_hex({"records": payload})


__all__ = [
    "PaperRecord",
    "assemble_paper_record",
    "assemble_no_trade_record",
    "paper_records_digest",
]
