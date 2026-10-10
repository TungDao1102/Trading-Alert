"""SHADOW decision history as `analytics-evidence/2` paper records (Phase 16, plan 16-36, D-18).

Research Pitfall P15: the operational SHADOW rows (signal, trade plan, approval, orders, fills and
the D041 confirm step) had no path into the Phase 10 reporting inputs. `export_shadow_evidence`
maps each SHADOW signal to its `PaperRecord` rows through `assemble_paper_record` (plan 16-35) and
lays them out in the evidence file the existing analytics CLI reads, so the journal-depth report
shows system, user-executed-sim and opportunity outcomes of the soak without any new metric
(D-18). The soak evidence never feeds a value into trading logic.

Pure: no I/O, no clock. The caller writes `evidence_file_bytes(document)` to disk. The file is
real evidence: it carries no `evidence_class` key, so the kill-gate report guard (plan 16-05)
applies to it. `test_only` rehearsal rows keep their flag; the analytics normalizer excludes and
counts them (REV-03, D063 item 3).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.domain.canonical import canonical_bytes

from .attribution import ShadowOutcome
from .journal import SHADOW_MODE, PaperRecord, assemble_paper_record, canonical_record_dict

# Repeated literal on purpose: the pure paper package does not import the adapter layer. A test
# pins it to `src.adapters.analytics_files.EVIDENCE_SCHEMA`.
EVIDENCE_FILE_SCHEMA = "analytics-evidence/2"


@dataclass(frozen=True)
class ShadowRow:
    """The journaled facts of one SHADOW plan, as `assemble_paper_record` takes them.

    - `signal` / `trade_plan`: the signal and trade plan dicts (identity and detection time).
    - `approval`: the approval row dict (`action`, `requested_at_utc`, `acted_at_utc`) or None
      when nobody touched the plan.
    - `order` / `fill`: the simulated entry order and fill, present only for APPROVE then CONFIRM.
    - `confirm`: `confirm_requested_at_utc` / `confirmed_at_utc` of the D041 confirm step.
    - `shadow_outcome`: the terminal outcome read from the journal. It is required: the exporter
      never guesses what happened to a plan.
    - `test_only`: True for a rehearsal row produced by a test (REV-03).
    """

    epoch_id: str
    signal: Mapping[str, Any]
    trade_plan: Mapping[str, Any]
    shadow_outcome: ShadowOutcome
    approval: Mapping[str, Any] | None = None
    order: Mapping[str, Any] | None = None
    fill: Mapping[str, Any] | None = None
    confirm: Mapping[str, Any] | None = None
    test_only: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.shadow_outcome, ShadowOutcome):
            raise ValueError("shadow_outcome must be a ShadowOutcome")
        if not isinstance(self.test_only, bool):
            raise ValueError("test_only must be a bool")


def _records_of(row: ShadowRow) -> list[PaperRecord]:
    return assemble_paper_record(
        epoch_id=row.epoch_id,
        signal=dict(row.signal),
        trade_plan=dict(row.trade_plan),
        approval=None if row.approval is None else dict(row.approval),
        order=None if row.order is None else dict(row.order),
        fill=None if row.fill is None else dict(row.fill),
        mode=SHADOW_MODE,
        confirm=None if row.confirm is None else dict(row.confirm),
        test_only=row.test_only,
        shadow_outcome=row.shadow_outcome,
    )


def export_shadow_evidence(
    rows: Sequence[ShadowRow],
    *,
    research_universe: Sequence[str],
    backtest_entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """The `analytics-evidence/2` document of the SHADOW rows (existing fields only, D-18).

    `research_universe` and `backtest_entries` are the required `research_universe` and
    `backtest` parts of the evidence file; the caller supplies them (the trial export of plan
    16-30 passes its experiment records). Paper records are ordered by signal id and
    attribution, so the document does not depend on the order of `rows`. Two rows for one
    signal are refused.
    """
    universe = list(research_universe)
    if not universe or any(not isinstance(symbol, str) or symbol == "" for symbol in universe):
        raise ValueError("research_universe must be a non-empty list of symbols")
    entries = [dict(entry) for entry in backtest_entries]
    seen: set[str] = set()
    records: list[PaperRecord] = []
    for row in rows:
        signal_id = row.signal["signal_id"]
        if signal_id in seen:
            raise ValueError(f"duplicate signal {signal_id!r} in the SHADOW rows")
        seen.add(signal_id)
        records.extend(_records_of(row))
    records.sort(key=lambda record: (record.signal_id or "", record.attribution.value))
    return {
        "schema": EVIDENCE_FILE_SCHEMA,
        "backtest": copy.deepcopy(entries),
        "paper": [canonical_record_dict(record) for record in records],
        "research_universe": sorted(set(universe)),
    }


def evidence_file_bytes(document: Mapping[str, Any]) -> bytes:
    """Canonical JSON bytes of an evidence document plus one line feed (byte-stable, D-18)."""
    return canonical_bytes(dict(document)) + b"\n"


__all__ = [
    "EVIDENCE_FILE_SCHEMA",
    "ShadowRow",
    "evidence_file_bytes",
    "export_shadow_evidence",
]
