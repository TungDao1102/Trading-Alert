"""Three-way attribution journaling tests (Phase 7, plan 07-03).

Per D-03: every paper record carries the canonical identity tuple
(strategyVersion + parameterSetId + parameterSetHash + experiment linkage
+ SignalId/plan hash + epoch_id) plus the full timestamp lineage
(signal/approve(simulated)/order(fill-simulated)/fill). Attribution
splits three ways: system (engine emitted), user-executed-sim (SIMULATE
fill with approval-delay modeling), and opportunity (skipped/expired
plans retained with reason codes — never dropped).

The tests load the golden fixture pair (input.json + expected.json)
from `tests/fixtures/phase7/attribution_split/` and
`tests/fixtures/phase7/opportunity_retained/`, feed the cases through
`assemble_paper_record` / `assemble_no_trade_record`, and assert:

  1. AttributionKind has exactly the three verbatim values
     `system`, `user-executed-sim`, `opportunity`.
  2. The simulated approval `acted_at_utc` equals
     `signal.detected_at_utc + APPROVAL_DELAY_LAG_SECONDS` (the
     approval-delay lag constant modeling the user-executed-sim leg).
  3. The caller-supplied `epoch_id` is carried on every assembled row.
  4. Skipped and expired plans persist as system + opportunity row
     pairs with reason codes intact (never dropped, never one row).
  5. NO_TRADE yields a single system row with the reason code and no
     SignalId.
  6. The canonical digest of the assembled rows equals the pinned
     expected digest (regression check).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

PHASE7_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase7"


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _load_input(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "input.json").read_text(encoding="utf-8"))


def _load_expected(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))


def _parse_utc(raw: str) -> datetime:
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise ValueError(f"naive datetime in fixture: {raw!r}")
    return value.astimezone(UTC)


def _coerce_money(value: object, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        return Decimal(value)
    if isinstance(value, int):
        return Decimal(value)
    raise TypeError(f"{field_name} must be Decimal/str/int, got {type(value).__name__}")


# --------------------------------------------------------------------------- #
# Test 1 — AttributionKind vocabulary is exactly three verbatim values.
# --------------------------------------------------------------------------- #


def test_attribution_kind_has_exactly_three_verbatim_values() -> None:
    """Beh. 1: AttributionKind has exactly the three canonical values.

    Per D-03: the attribution enum is the canonical vocabulary for
    system vs user-executed-sim vs opportunity. The values are
    byte-exact: `system`, `user-executed-sim`, `opportunity`. No
    synonyms, no invented names — an unknown value is a load-time
    error.
    """
    from src.paper.attribution import AttributionKind

    values = {member.value for member in AttributionKind}
    assert values == {"system", "user-executed-sim", "opportunity"}, (
        f"AttributionKind values must be exactly {{'system', 'user-executed-sim', 'opportunity'}}, "
        f"got {values}"
    )


# --------------------------------------------------------------------------- #
# Test 2 — APPROVAL_DELAY_LAG_SECONDS is a positive integer constant.
# --------------------------------------------------------------------------- #


def test_approval_delay_lag_seconds_is_documented_constant() -> None:
    """Beh. 2: APPROVAL_DELAY_LAG_SECONDS is a positive integer.

    Per D-03 (FLAGGED ASSUMPTION, PAPER-02 unclassified): the
    approval-delay lag constant modeling the user-executed-sim leg is
    a fixed documented value in attribution.py, flagged for Phase-10
    calibration against measured Telegram latency. The constant must
    be a positive integer (seconds).
    """
    from src.paper.attribution import APPROVAL_DELAY_LAG_SECONDS

    assert isinstance(APPROVAL_DELAY_LAG_SECONDS, int)
    assert APPROVAL_DELAY_LAG_SECONDS > 0


# --------------------------------------------------------------------------- #
# Test 3 — assemble_paper_record on the filled-simulation case yields
# system + user-executed-sim rows with the lag applied.
# --------------------------------------------------------------------------- #


def test_assemble_paper_record_filled_simulation_yields_system_and_user_executed_sim() -> None:
    """Beh. 3: a SETUP filled in simulation yields two rows.

    Per D-03: a SETUP that was filled in simulation produces:
      - one `system` row (the engine emission)
      - one `user-executed-sim` row (the SIMULATE fill leg with the
        approval-delay lag applied to the simulated `acted_at_utc`)

    The simulated approval `acted_at_utc` must equal
    `signal.detected_at_utc + APPROVAL_DELAY_LAG_SECONDS` exactly.
    The caller-supplied `epoch_id` must appear on both rows.
    """
    from src.paper.attribution import APPROVAL_DELAY_LAG_SECONDS, AttributionKind
    from src.paper.journal import assemble_paper_record

    case_dir = PHASE7_FIXTURES_DIR / "attribution_split"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    filled_case = next(c for c in case_input["cases"] if c["kind"] == "filled_simulation")
    epoch_id = case_input["epoch_id"]

    records = assemble_paper_record(
        epoch_id=epoch_id,
        signal=filled_case["signal"],
        trade_plan=filled_case["trade_plan"],
        approval=filled_case["approval"],
        order=filled_case["order"],
        fill=filled_case["fill"],
    )

    assert len(records) == expected["row_counts"]["filled_simulation"], (
        f"filled_simulation must yield {expected['row_counts']['filled_simulation']} rows, "
        f"got {len(records)}"
    )

    attributions = [r.attribution for r in records]
    assert attributions == [
        AttributionKind.SYSTEM,
        AttributionKind.USER_EXECUTED_SIM,
    ], f"filled_simulation attributions must be [system, user-executed-sim], got {attributions}"

    # The simulated approval acted_at_utc must equal signal time + lag.
    signal_detected = _parse_utc(filled_case["signal"]["detected_at_utc"])
    expected_acted = signal_detected + timedelta(seconds=APPROVAL_DELAY_LAG_SECONDS)
    sim_record = records[1]
    assert sim_record.approval_acted_at_utc == expected_acted, (
        f"simulated approval acted_at_utc must equal signal time + APPROVAL_DELAY_LAG_SECONDS, "
        f"got {sim_record.approval_acted_at_utc} != {expected_acted}"
    )

    # The caller-supplied epoch_id must appear on every row.
    for record in records:
        assert record.epoch_id == epoch_id, (
            f"epoch_id must be carried on every row, got {record.epoch_id} != {epoch_id}"
        )


# --------------------------------------------------------------------------- #
# Test 4 — assemble_paper_record on the skipped case yields system +
# opportunity rows with the skip reason code.
# --------------------------------------------------------------------------- #


def test_assemble_paper_record_skipped_yields_system_and_opportunity() -> None:
    """Beh. 4: a skipped plan yields two rows with the skip reason.

    Per D-03: a SETUP that was skipped (caller-reported SKIP_USER or
    SKIP_BUSY) persists as:
      - one `system` row (the engine emission)
      - one `opportunity` row carrying the skip reason code

    Both rows retain SignalId, plan hash, and full lineage. The
    opportunity row's reason code must equal the skip reason.
    """
    from src.paper.attribution import AttributionKind
    from src.paper.journal import assemble_paper_record

    case_dir = PHASE7_FIXTURES_DIR / "attribution_split"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    skipped_case = next(c for c in case_input["cases"] if c["kind"] == "skipped")
    epoch_id = case_input["epoch_id"]

    records = assemble_paper_record(
        epoch_id=epoch_id,
        signal=skipped_case["signal"],
        trade_plan=skipped_case["trade_plan"],
        approval=None,
        order=None,
        fill=None,
        skip_reason=skipped_case["skip_reason"],
    )

    assert len(records) == expected["row_counts"]["skipped"], (
        f"skipped must yield {expected['row_counts']['skipped']} rows, got {len(records)}"
    )

    attributions = [r.attribution for r in records]
    assert attributions == [
        AttributionKind.SYSTEM,
        AttributionKind.OPPORTUNITY,
    ], f"skipped attributions must be [system, opportunity], got {attributions}"

    # The opportunity row must carry the skip reason code.
    opp_record = records[1]
    assert opp_record.reason_code == expected["skip_reason_code"], (
        f"opportunity row reason_code must be {expected['skip_reason_code']!r}, "
        f"got {opp_record.reason_code!r}"
    )

    # Both rows must retain SignalId and plan hash.
    for record in records:
        assert record.signal_id == skipped_case["signal"]["signal_id"]
        assert record.plan_hash == skipped_case["trade_plan"]["plan_hash"]
        assert record.epoch_id == epoch_id


# --------------------------------------------------------------------------- #
# Test 5 — assemble_paper_record on the expired case yields system +
# opportunity rows with EXPIRED.
# --------------------------------------------------------------------------- #


def test_assemble_paper_record_expired_yields_system_and_opportunity() -> None:
    """Beh. 5: an expired plan yields two rows with EXPIRED.

    Per D-03: a SETUP that expired (now_utc past expires_at_utc
    without fill) persists as:
      - one `system` row (the engine emission)
      - one `opportunity` row with reason code EXPIRED

    Both rows retain SignalId, plan hash, and full lineage.
    """
    from src.paper.attribution import AttributionKind
    from src.paper.journal import assemble_paper_record

    case_dir = PHASE7_FIXTURES_DIR / "attribution_split"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    expired_case = next(c for c in case_input["cases"] if c["kind"] == "expired")
    epoch_id = case_input["epoch_id"]

    records = assemble_paper_record(
        epoch_id=epoch_id,
        signal=expired_case["signal"],
        trade_plan=expired_case["trade_plan"],
        approval=None,
        order=None,
        fill=None,
        expired_at_utc=expired_case["expired_at_utc"],
    )

    assert len(records) == expected["row_counts"]["expired"], (
        f"expired must yield {expected['row_counts']['expired']} rows, got {len(records)}"
    )

    attributions = [r.attribution for r in records]
    assert attributions == [
        AttributionKind.SYSTEM,
        AttributionKind.OPPORTUNITY,
    ], f"expired attributions must be [system, opportunity], got {attributions}"

    # The opportunity row must carry the EXPIRED reason code.
    opp_record = records[1]
    assert opp_record.reason_code == expected["expired_reason_code"], (
        f"opportunity row reason_code must be {expected['expired_reason_code']!r}, "
        f"got {opp_record.reason_code!r}"
    )

    # Both rows must retain SignalId and plan hash.
    for record in records:
        assert record.signal_id == expired_case["signal"]["signal_id"]
        assert record.plan_hash == expired_case["trade_plan"]["plan_hash"]
        assert record.epoch_id == epoch_id


# --------------------------------------------------------------------------- #
# Test 6 — assemble_no_trade_record yields a single system row with the
# reason code and no SignalId.
# --------------------------------------------------------------------------- #


def test_assemble_no_trade_record_yields_single_system_row() -> None:
    """Beh. 6: a NO_TRADE outcome yields one system row.

    Per D-03: a NO_TRADE (no signal emitted) yields a single `system`
    row with the reason code and no SignalId. The row carries the
    epoch_id and the canonical identity tuple (minus SignalId/plan
    hash which don't exist for a NO_TRADE).
    """
    from src.paper.attribution import AttributionKind
    from src.paper.journal import assemble_no_trade_record

    case_dir = PHASE7_FIXTURES_DIR / "attribution_split"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    no_trade_case = next(c for c in case_input["cases"] if c["kind"] == "no_trade")
    epoch_id = case_input["epoch_id"]

    record = assemble_no_trade_record(
        epoch_id=epoch_id,
        strategy_id=no_trade_case["strategy_id"],
        strategy_version=no_trade_case["strategy_version"],
        parameter_set_id=no_trade_case["parameter_set_id"],
        parameter_set_hash=no_trade_case["parameter_set_hash"],
        experiment_id=no_trade_case["experiment_id"],
        symbol=no_trade_case["symbol"],
        reason_code=no_trade_case["no_trade_reason_code"],
    )

    assert record.attribution == AttributionKind.SYSTEM
    assert record.reason_code == expected["no_trade_reason_code"]
    assert record.signal_id is None
    assert record.plan_hash is None
    assert record.epoch_id == epoch_id
    assert record.strategy_id == no_trade_case["strategy_id"]
    assert record.parameter_set_id == no_trade_case["parameter_set_id"]
    assert record.parameter_set_hash == no_trade_case["parameter_set_hash"]
    assert record.experiment_id == no_trade_case["experiment_id"]
    assert record.symbol == no_trade_case["symbol"]


# --------------------------------------------------------------------------- #
# Test 7 — canonical identity fields are carried on every row.
# --------------------------------------------------------------------------- #


def test_canonical_identity_fields_carried_on_every_row() -> None:
    """Beh. 7: every assembled row carries the canonical identity tuple.

    Per D-03: the canonical identity tuple is
    (strategyVersion, parameterSetId, parameterSetHash, experiment
    linkage, SignalId, plan hash, epoch_id). Every row — system,
    user-executed-sim, opportunity — must carry these fields.
    """
    from src.paper.journal import assemble_paper_record

    case_dir = PHASE7_FIXTURES_DIR / "attribution_split"
    case_input = _load_input(case_dir)
    epoch_id = case_input["epoch_id"]

    filled_case = next(c for c in case_input["cases"] if c["kind"] == "filled_simulation")
    records = assemble_paper_record(
        epoch_id=epoch_id,
        signal=filled_case["signal"],
        trade_plan=filled_case["trade_plan"],
        approval=filled_case["approval"],
        order=filled_case["order"],
        fill=filled_case["fill"],
    )

    for record in records:
        assert record.strategy_version == filled_case["strategy_version"]
        assert record.parameter_set_id == filled_case["parameter_set_id"]
        assert record.parameter_set_hash == filled_case["parameter_set_hash"]
        assert record.experiment_id == filled_case["experiment_id"]
        assert record.signal_id == filled_case["signal"]["signal_id"]
        assert record.plan_hash == filled_case["trade_plan"]["plan_hash"]
        assert record.epoch_id == epoch_id


# --------------------------------------------------------------------------- #
# Test 8 — full timestamp lineage is carried on the user-executed-sim row.
# --------------------------------------------------------------------------- #


def test_full_timestamp_lineage_on_user_executed_sim_row() -> None:
    """Beh. 8: the user-executed-sim row carries the full timestamp lineage.

    Per D-03: the timestamp lineage is
    (signal detected_at_utc, approve simulated acted_at_utc,
    order fill-simulated timestamps, fill timestamp). The
    user-executed-sim row must carry all four timestamps.
    """
    from src.paper.journal import assemble_paper_record

    case_dir = PHASE7_FIXTURES_DIR / "attribution_split"
    case_input = _load_input(case_dir)

    filled_case = next(c for c in case_input["cases"] if c["kind"] == "filled_simulation")
    epoch_id = case_input["epoch_id"]

    records = assemble_paper_record(
        epoch_id=epoch_id,
        signal=filled_case["signal"],
        trade_plan=filled_case["trade_plan"],
        approval=filled_case["approval"],
        order=filled_case["order"],
        fill=filled_case["fill"],
    )

    sim_record = records[1]
    assert sim_record.signal_detected_at_utc == _parse_utc(
        filled_case["signal"]["detected_at_utc"]
    )
    assert sim_record.approval_acted_at_utc is not None
    assert sim_record.order_submitted_at_utc == _parse_utc(
        filled_case["order"]["submitted_at_utc"]
    )
    assert sim_record.fill_time_utc == _parse_utc(filled_case["fill"]["fill_time_utc"])


# --------------------------------------------------------------------------- #
# Test 9 — canonical digest of assembled rows equals expected.json.
# --------------------------------------------------------------------------- #


def test_canonical_digest_equals_expected() -> None:
    """Beh. 9: the canonical digest of assembled rows equals expected.

    Per D-03: the assembled rows form a canonical-JSON-safe digest
    that must equal the pinned expected digest. Any change to the
    assembly contract (field order, serialization, identity tuple)
    fails this test.
    """
    from src.paper.journal import (
        assemble_no_trade_record,
        assemble_paper_record,
        paper_records_digest,
    )

    case_dir = PHASE7_FIXTURES_DIR / "attribution_split"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    epoch_id = case_input["epoch_id"]
    all_records: list[Any] = []

    for case in case_input["cases"]:
        if case["kind"] == "no_trade":
            record = assemble_no_trade_record(
                epoch_id=epoch_id,
                strategy_id=case["strategy_id"],
                strategy_version=case["strategy_version"],
                parameter_set_id=case["parameter_set_id"],
                parameter_set_hash=case["parameter_set_hash"],
                experiment_id=case["experiment_id"],
                symbol=case["symbol"],
                reason_code=case["no_trade_reason_code"],
            )
            all_records.append(record)
        else:
            records = assemble_paper_record(
                epoch_id=epoch_id,
                signal=case["signal"],
                trade_plan=case["trade_plan"],
                approval=case.get("approval"),
                order=case.get("order"),
                fill=case.get("fill"),
                skip_reason=case.get("skip_reason"),
                expired_at_utc=case.get("expired_at_utc"),
            )
            all_records.extend(records)

    digest = paper_records_digest(all_records)
    assert digest == expected["digest"], (
        f"assembled digest {digest} != expected {expected['digest']}"
    )


# --------------------------------------------------------------------------- #
# Test 10 — opportunity retention: skipped plans persist with reason codes.
# --------------------------------------------------------------------------- #


def test_opportunity_retained_skipped_plans_persist_with_reason() -> None:
    """Beh. 10: skipped plans persist as system + opportunity row pairs.

    Per D-03 (never-dropped rule): skipped plans persist as
    system + opportunity row pairs with reason codes intact. No
    plan outcome is ever dropped to flatter the record.
    """
    from src.paper.attribution import AttributionKind
    from src.paper.journal import assemble_paper_record

    case_dir = PHASE7_FIXTURES_DIR / "opportunity_retained"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    epoch_id = case_input["epoch_id"]
    skip_case = next(c for c in case_input["cases"] if c["kind"] == "skipped")

    records = assemble_paper_record(
        epoch_id=epoch_id,
        signal=skip_case["signal"],
        trade_plan=skip_case["trade_plan"],
        approval=None,
        order=None,
        fill=None,
        skip_reason=skip_case["skip_reason"],
    )

    assert len(records) == 2, (
        f"skipped plan must yield exactly 2 rows (system + opportunity), got {len(records)}"
    )
    assert records[0].attribution == AttributionKind.SYSTEM
    assert records[1].attribution == AttributionKind.OPPORTUNITY
    assert records[1].reason_code == expected["skip_reason_code"]
    # Both rows must retain SignalId and plan hash.
    for record in records:
        assert record.signal_id == skip_case["signal"]["signal_id"]
        assert record.plan_hash == skip_case["trade_plan"]["plan_hash"]


# --------------------------------------------------------------------------- #
# Test 11 — opportunity retention: expired plans persist with EXPIRED.
# --------------------------------------------------------------------------- #


def test_opportunity_retained_expired_plans_persist_with_expired() -> None:
    """Beh. 11: expired plans persist as system + opportunity row pairs.

    Per D-03 (never-dropped rule): expired plans persist as
    system + opportunity row pairs with reason code EXPIRED.
    """
    from src.paper.attribution import AttributionKind
    from src.paper.journal import assemble_paper_record

    case_dir = PHASE7_FIXTURES_DIR / "opportunity_retained"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    epoch_id = case_input["epoch_id"]
    expired_case = next(c for c in case_input["cases"] if c["kind"] == "expired")

    records = assemble_paper_record(
        epoch_id=epoch_id,
        signal=expired_case["signal"],
        trade_plan=expired_case["trade_plan"],
        approval=None,
        order=None,
        fill=None,
        expired_at_utc=expired_case["expired_at_utc"],
    )

    assert len(records) == 2, (
        f"expired plan must yield exactly 2 rows (system + opportunity), got {len(records)}"
    )
    assert records[0].attribution == AttributionKind.SYSTEM
    assert records[1].attribution == AttributionKind.OPPORTUNITY
    assert records[1].reason_code == expected["expired_reason_code"]
    # Both rows must retain SignalId and plan hash.
    for record in records:
        assert record.signal_id == expired_case["signal"]["signal_id"]
        assert record.plan_hash == expired_case["trade_plan"]["plan_hash"]


# --------------------------------------------------------------------------- #
# Test 12 — PaperRecord rejects empty identity fields and naive datetimes.
# --------------------------------------------------------------------------- #


def test_paper_record_rejects_empty_identity_and_naive_datetimes() -> None:
    """Beh. 12: PaperRecord validates identity completeness and UTC awareness.

    Per D-12: empty identity fields and naive datetimes are rejected
    at construction. The assembler must validate before persisting.
    """
    from src.paper.attribution import AttributionKind
    from src.paper.journal import PaperRecord

    # Empty epoch_id must raise.
    try:
        PaperRecord(
            attribution=AttributionKind.SYSTEM,
            epoch_id="",
            strategy_id="trend-pullback",
            strategy_version="v2.0.0",
            parameter_set_id="baseline-v3",
            parameter_set_hash="hash",
            experiment_id="exp",
            symbol="BTCUSDT",
            signal_id=None,
            plan_hash=None,
            reason_code="DATA_STALE",
            signal_detected_at_utc=None,
            approval_acted_at_utc=None,
            order_submitted_at_utc=None,
            fill_time_utc=None,
        )
        assert False, "empty epoch_id must raise ValueError"
    except ValueError:
        pass

    # Naive datetime must raise.
    try:
        PaperRecord(
            attribution=AttributionKind.SYSTEM,
            epoch_id="epoch-1",
            strategy_id="trend-pullback",
            strategy_version="v2.0.0",
            parameter_set_id="baseline-v3",
            parameter_set_hash="hash",
            experiment_id="exp",
            symbol="BTCUSDT",
            signal_id=None,
            plan_hash=None,
            reason_code="DATA_STALE",
            signal_detected_at_utc=datetime(2026, 9, 19, 10, 0, 0),  # naive!
            approval_acted_at_utc=None,
            order_submitted_at_utc=None,
            fill_time_utc=None,
        )
        assert False, "naive datetime must raise ValueError"
    except ValueError:
        pass
