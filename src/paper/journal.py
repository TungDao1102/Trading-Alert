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
from datetime import UTC, datetime, timedelta
from typing import Any

from src.domain.canonical import sha256_hex

from .attribution import APPROVAL_DELAY_LAG_SECONDS, AttributionKind

# The only mode a Phase 16 record may carry (D-15). A record without a mode is a production-path
# record of Phases 7 to 10 and keeps its canonical form byte for byte.
SHADOW_MODE = "SHADOW"

# Approval actions that are a real human decision (GLOSSARY section 4). SIMULATE is the paper
# simulator's own approval leg: no human acted, so the documented constant applies.
_HUMAN_ACTIONS = frozenset({"APPROVE", "SKIP_USER", "SKIP_BUSY", "CANCEL"})

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
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


def _require_not_before(
    earlier: datetime | None, later: datetime | None, later_name: str, earlier_name: str
) -> None:
    if earlier is not None and later is not None and later < earlier:
        raise ValueError(f"{later_name} is before {earlier_name}")


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

    Phase 16 (plan 16-35, D-15) adds optional SHADOW fields, all omitted
    from the canonical output when absent so every earlier digest is
    unchanged:
      - `mode`: None for the Phase 7 to 10 production-path records, "SHADOW"
        for a record of the SHADOW chain.
      - `approval_requested_at_utc`: when the approval was requested; with
        `approval_acted_at_utc` it gives the measured approval delay.
      - `confirm_requested_at_utc` / `confirmed_at_utc`: the D041 confirm step.
      - `test_only`: True marks a record produced by a test; written only when
        True (absent means a production record).
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
    mode: str | None = None
    approval_requested_at_utc: datetime | None = None
    confirm_requested_at_utc: datetime | None = None
    confirmed_at_utc: datetime | None = None
    test_only: bool = False

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
        # Plan 16-35 SHADOW fields (all optional).
        if self.mode is not None and self.mode != SHADOW_MODE:
            raise ValueError(f"mode must be None or {SHADOW_MODE!r}, got {self.mode!r}")
        if not isinstance(self.test_only, bool):
            raise ValueError("test_only must be a bool")
        _require_utc_aware(self.approval_requested_at_utc, "approval_requested_at_utc")
        _require_utc_aware(self.confirm_requested_at_utc, "confirm_requested_at_utc")
        _require_utc_aware(self.confirmed_at_utc, "confirmed_at_utc")
        _require_not_before(
            self.approval_requested_at_utc,
            self.approval_acted_at_utc,
            "approval_acted_at_utc",
            "approval_requested_at_utc",
        )
        _require_not_before(
            self.confirm_requested_at_utc,
            self.confirmed_at_utc,
            "confirmed_at_utc",
            "confirm_requested_at_utc",
        )


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
    return value.astimezone(tz=UTC)


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


def _is_human_action(approval: dict[str, Any]) -> bool:
    """True when the approval row records a real human decision (D-15).

    A missing or unknown `action` fails closed: guessing "no human" would put the 30 s
    constant where a measured delay belongs.
    """
    action = approval.get("action")
    if action in _HUMAN_ACTIONS:
        return True
    if action == "SIMULATE":
        return False
    raise ValueError(f"approval['action'] must name an approval action, got {action!r}")


def _measured_approval(approval: dict[str, Any]) -> tuple[datetime, datetime]:
    """The measured (requested, acted) pair of a human approval row."""
    requested = _parse_utc(approval.get("requested_at_utc"))
    if requested is None:
        raise ValueError("a human action needs approval['requested_at_utc'] to measure the delay")
    acted = _parse_utc(approval.get("acted_at_utc"))
    if acted is None:
        raise ValueError(
            "a human action needs approval['acted_at_utc']: the constant lag is only for "
            "records with no human action"
        )
    if acted < requested:
        raise ValueError("approval acted_at_utc is before requested_at_utc")
    return requested, acted


def _confirm_timestamps(
    confirm: dict[str, Any] | None, acted_at_utc: datetime
) -> tuple[datetime, datetime]:
    """The (confirm_requested, confirmed) pair a filled SHADOW record must carry."""
    if confirm is None:
        raise ValueError("a filled SHADOW record needs the confirm timestamps")
    issued = _parse_utc(confirm.get("confirm_requested_at_utc"))
    confirmed = _parse_utc(confirm.get("confirmed_at_utc"))
    if issued is None or confirmed is None:
        raise ValueError(
            "a filled SHADOW record needs confirm_requested_at_utc and confirmed_at_utc"
        )
    if issued < acted_at_utc:
        raise ValueError("confirm_requested_at_utc is before the approval acted_at_utc")
    if confirmed < issued:
        raise ValueError("confirmed_at_utc is before confirm_requested_at_utc")
    return issued, confirmed


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
    mode: str | None = None,
    confirm: dict[str, Any] | None = None,
    test_only: bool = False,
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

    Phase 16 (plan 16-35, D-15, SC3): with `mode="SHADOW"` and an approval
    row that records a real human action (`action` APPROVE, SKIP_USER,
    SKIP_BUSY or CANCEL), the approval delay is the measured
    `acted_at_utc - requested_at_utc` of that row and the `confirm` mapping
    (`confirm_requested_at_utc`, `confirmed_at_utc`) is carried on the
    user-executed-sim row; the signal + `APPROVAL_DELAY_LAG_SECONDS`
    constant is used only for a record with no human action (SIMULATE).
    Without `mode` the behaviour is exactly that of Phases 7 to 10.

    The function is a pure function of its inputs — no I/O, no clock
    reads, no randomness. The ORM layer maps these records onto
    existing seven-entity rows via `src/db/mappers.py` (D-02 single-Base
    ORM discipline, no new tables).
    """
    if mode is not None and mode != SHADOW_MODE:
        raise ValueError(f"mode must be None or {SHADOW_MODE!r}, got {mode!r}")
    if test_only and mode != SHADOW_MODE:
        raise ValueError("test_only is only valid for mode='SHADOW'")
    if confirm is not None and mode != SHADOW_MODE:
        raise ValueError("confirm timestamps are only valid for mode='SHADOW'")

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
    if signal_detected_at_utc is None:
        raise ValueError("signal['detected_at_utc'] must be present")

    # Outcome-shape validation (WR-05): ambiguous or partial inputs
    # fail loudly with dedicated messages instead of falling through
    # to the generic case-mismatch error.
    if skip_reason is not None and expired_at_utc is not None:
        raise ValueError("ambiguous outcome: skip_reason and expired_at_utc both set")
    if skip_reason is not None and not skip_reason:
        raise ValueError("skip_reason must be a non-empty string")

    # Case 1: filled in simulation — system + user-executed-sim.
    if approval is not None and order is not None and fill is not None:
        if skip_reason is not None or expired_at_utc is not None:
            raise ValueError("ambiguous outcome: filled legs with skip_reason/expired_at_utc set")
        human = mode == SHADOW_MODE and _is_human_action(approval)
        approval_requested_at_utc: datetime | None = None
        confirm_requested_at_utc: datetime | None = None
        confirmed_at_utc: datetime | None = None
        if human:
            if approval.get("action") != "APPROVE":
                raise ValueError(
                    f"filled legs need an APPROVE human action, got {approval.get('action')!r}"
                )
            approval_requested_at_utc, simulated_acted_at_utc = _measured_approval(approval)
            confirm_requested_at_utc, confirmed_at_utc = _confirm_timestamps(
                confirm, simulated_acted_at_utc
            )
        else:
            # No human action: the simulated approval acted_at_utc equals signal time + lag.
            simulated_acted_at_utc = signal_detected_at_utc + timedelta(
                seconds=APPROVAL_DELAY_LAG_SECONDS
            )
            # Cross-check a caller-supplied approval timestamp (WR-05a):
            # silently ignoring a disagreeing acted_at_utc hides caller
            # confusion about who owns approval timing (the assembler does).
            raw_acted = approval.get("acted_at_utc")
            if raw_acted is not None:
                caller_acted = _parse_utc(raw_acted)
                if caller_acted != simulated_acted_at_utc:
                    raise ValueError(
                        "approval['acted_at_utc'] disagrees with the simulated "
                        f"signal+lag time: {raw_acted!r} != "
                        f"{simulated_acted_at_utc.isoformat()}"
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
            mode=mode,
            test_only=test_only,
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
            mode=mode,
            approval_requested_at_utc=approval_requested_at_utc,
            confirm_requested_at_utc=confirm_requested_at_utc,
            confirmed_at_utc=confirmed_at_utc,
            test_only=test_only,
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

    # No valid case matched — fail closed. A partial leg (some of
    # approval/order/fill present without skip/expired) gets its own
    # PARTIAL_LEG rejection instead of the generic message (WR-05b).
    if approval is not None or order is not None or fill is not None:
        raise ValueError(
            "PARTIAL_LEG: approval/order/fill must be all present (filled) "
            "or all absent with skip_reason/expired_at_utc"
        )
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
    SignalId/plan hash which don't exist for a NO_TRADE). Empty reason
    codes are rejected (WR-05d) — an opportunity/NO_TRADE row without
    a reason is an audit hole.
    """
    if not reason_code:
        raise ValueError("reason_code must be a non-empty string")
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


def canonical_record_dict(record: PaperRecord) -> dict[str, Any]:
    """The canonical-JSON-safe dict of one record, the unit of `paper_records_digest`.

    The fifteen Phase 7 keys come first, in their original order. The Phase 16 SHADOW keys
    (`mode`, `approval_requested_at_utc`, `confirm_requested_at_utc`, `confirmed_at_utc`,
    `test_only`) are written only when set, so a record without them hashes exactly as it did
    before plan 16-35 (T-16-82).
    """

    def _iso(value: datetime | None) -> str | None:
        return None if value is None else value.isoformat()

    out: dict[str, Any] = {
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
        "signal_detected_at_utc": _iso(record.signal_detected_at_utc),
        "approval_acted_at_utc": _iso(record.approval_acted_at_utc),
        "order_submitted_at_utc": _iso(record.order_submitted_at_utc),
        "fill_time_utc": _iso(record.fill_time_utc),
    }
    if record.mode is not None:
        out["mode"] = record.mode
    for name in ("approval_requested_at_utc", "confirm_requested_at_utc", "confirmed_at_utc"):
        value = getattr(record, name)
        if value is not None:
            out[name] = value.isoformat()
    if record.test_only:
        out["test_only"] = True
    return out


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
    payload = [canonical_record_dict(record) for record in records]
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
    "SHADOW_MODE",
    "PaperRecord",
    "canonical_record_dict",
    "assemble_paper_record",
    "assemble_no_trade_record",
    "paper_records_digest",
]
