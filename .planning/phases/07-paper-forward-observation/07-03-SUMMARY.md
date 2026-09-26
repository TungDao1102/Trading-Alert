# Phase 7 Plan 3: Paper Three-Way Attribution Journaling Summary

## One-liner

Three-way attribution journaling for the paper loop: canonical AttributionKind vocabulary, record assembler binding canonical identity plus full timestamp lineage onto existing seven-entity ORM shapes, and golden proof that system, user-executed-sim, and opportunity legs persist with reason codes intact.

## What Was Built

### Core modules

- `src/paper/attribution.py` — `AttributionKind` enum with exactly the three verbatim values `system`, `user-executed-sim`, `opportunity` (D-03 vocabulary lock). `APPROVAL_DELAY_LAG_SECONDS = 30` constant modeling the user-executed-sim leg, flagged for Phase-10 calibration against measured Telegram latency.
- `src/paper/journal.py` — `PaperRecord` frozen dataclass carrying the canonical identity tuple (strategyVersion + parameterSetId + parameterSetHash + experiment linkage + SignalId/plan hash + epoch_id) plus the full timestamp lineage (signal/approve(simulated)/order(fill-simulated)/fill). `__post_init__` rejects empty identity fields and naive datetimes (D-12 fail-closed posture). `assemble_paper_record` maps a loop outcome onto one or two PaperRecord instances:
  - Filled in simulation → `[system_row, user_executed_sim_row]` with the lag applied to the simulated `acted_at_utc`
  - Skipped → `[system_row, opportunity_row]` with the skip reason code
  - Expired → `[system_row, opportunity_row]` with `EXPIRED`
  - `assemble_no_trade_record` yields a single system row with the reason code and no SignalId/plan hash
  - `paper_records_digest` computes the canonical digest over the assembled rows for regression checking
- `src/paper/__init__.py` — barrel re-exporting the new public symbols

### Test fixtures (golden pairs)

- `tests/fixtures/phase7/attribution_split/` — one SETUP filled in simulation, one SETUP skipped, one SETUP expired, one NO_TRADE. Pinned digest `f17b3445673ef09b987c4d76fc0de598e4d0a375ef4750717743429441dacfcd`.
- `tests/fixtures/phase7/opportunity_retained/` — one skip case + one expiry case, asserting two rows per plan (system + opportunity pair, never one, never zero).

### Test suites

- `tests/test_paper_attribution.py` — 16 tests covering:
  1. AttributionKind has exactly three verbatim values
  2. APPROVAL_DELAY_LAG_SECONDS is a positive integer
  3. Filled simulation yields system + user-executed-sim rows with lag applied
  4. Skipped yields system + opportunity with skip reason
  5. Expired yields system + opportunity with EXPIRED
  6. NO_TRADE yields single system row with reason code
  7. Canonical identity fields carried on every row
  8. Full timestamp lineage on user-executed-sim row
  9. Canonical digest equals expected
  10. Opportunity retention: skipped plans persist
  11. Opportunity retention: expired plans persist
  12. PaperRecord rejects empty identity and naive datetimes
  13. ORM round-trip: system row → SignalRow + TradePlanRow
  14. ORM round-trip: user-executed-sim row → ApprovalRow with action=SIMULATE
  15. ORM round-trip: opportunity row → JournalEventRow
  16. Unknown attribution string raises ValueError on restore

## Key Decisions

### D-01: AttributionKind is a first-class vocabulary, not a post-hoc join

- The three values `system`, `user-executed-sim`, `opportunity` are byte-exact and must not be renamed
- Phase-10 analytics reads these values directly from journal rows
- The `str, Enum` mixin keeps ORM/JSON `.value` storage trivial while preserving Enum identity for mypy checks

### D-02: APPROVAL_DELAY_LAG_SECONDS is a fixed documented constant

- Models the user-executed-sim leg: simulated `acted_at_utc = signal.detected_at_utc + APPROVAL_DELAY_LAG_SECONDS`
- Flagged for Phase-10 calibration against measured Telegram latency (PAPER-02 unclassified)
- The value is a documented constant — not an env var — so a mid-soak change is a code change, not a config drift

### D-03: PaperRecord carries the full canonical identity tuple plus timestamp lineage

- Identity: strategyVersion + parameterSetId + parameterSetHash + experiment linkage + SignalId/plan hash + epoch_id
- Lineage: signal detected_at_utc, approve simulated acted_at_utc, order fill-simulated timestamps, fill timestamp
- Every row carries `epoch_id` (caller-supplied from `src/paper/freeze.py`) so future Parquet extraction partitioned by epoch is lossless
- Optional timestamps are `None` for "transition never happened" (D-11), never nullable Enum statuses

### D-04: Opportunity retention is structural, never post-hoc

- Skipped plans persist as system + opportunity row pairs (2 rows, never 1, never 0)
- Expired plans persist as system + opportunity row pairs with `EXPIRED` reason code
- No delete or overwrite path exists in journal.py (T-7-08 mitigation)
- Absence of evidence is itself evidence (per D-03 never-dropped rule)

### D-05: Single-Base ORM discipline with no migration

- PaperRecord maps onto existing seven-entity ORM rows via `src/db/mappers.py`
- No new tables, no new columns
- Approval action `SIMULATE` stored by value (D-10 boundary contract)
- JournalEventRow carries the attribution + reason_code in `payload_json`
- No Alembic migration file created by this plan

### D-06: Parquet extract pipeline explicitly deferred to Phase 10

- Every row already carries `epoch_id` plus the full canonical identity
- Deferred extraction loses nothing
- Rationale: Phase-7 acceptance rests on PostgreSQL operational rows plus golden fixtures; extracts are an analytics convenience

## Deviations from Plan

None — plan executed exactly as written.

## Test Results

- 16 paper attribution tests passing (vocabulary + assembly + opportunity retention + ORM round-trip)
- 2 no-float guard tests passing (extended scope)
- `ruff check` clean across `src/paper/attribution.py`, `src/paper/journal.py`, `src/paper/__init__.py`
- `mypy --strict` clean across `src/paper/attribution.py`, `src/paper/journal.py`, `src/paper/__init__.py`
- D-12 Decimal-only guard extended to cover new files

## Commits

- `35f21d6` — test(07-03): paper attribution red-phase fixtures and failing tests
- `ffc9a6e` — feat(07-03): paper attribution vocabulary plus record assembly
- `0986188` — chore(07-03): static gates for paper attribution slice
