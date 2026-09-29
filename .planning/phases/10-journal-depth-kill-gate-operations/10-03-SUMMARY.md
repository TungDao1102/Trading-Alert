---
phase: 10-journal-depth-kill-gate-operations
plan: 03
subsystem: analytics
tags: [analytics, execution-quality, latency, lifecycle, decimal, determinism, golden-fixtures, tdd]

requires:
  - phase: 10-journal-depth-kill-gate-operations
    provides: "10-01 analytics core: EvidenceKind, IncompleteReason, TradeOutcome, Estimate/DistStat, stats helpers (seconds_between, percent, dist_stat, seed_for), purity/typing guards"
  - phase: 07-paper-trading
    provides: "PaperRecord three-way attribution rows and APPROVAL_DELAY_LAG_SECONDS"
  - phase: 09-execution
    provides: "ENTRY_EXPIRY pre_cancel/post_cancel/cancel_failed journal events keyed by client_order_id"
provides:
  - "LifecycleRecord/LifecyclePath: one normalized per-signal lifecycle contract for paper, backtest and live evidence"
  - "normalize_paper_lifecycle / normalize_backtest_lifecycle / normalize_live_lifecycle (with JoinAccount and LiveLifecycleResult join + rejected accounting)"
  - "build_execution_quality: digest-stamped ExecutionQualitySection with six fixed-order latency legs, fill %, expiry-without-fill rate, signed entry deviation (price and bps)"
affects: [10-04, 10-05, 10-06, 10-07, 10-08, 10-09, 10-10, 10-11, 10-12]

actuals:
  tokens: 24000
  tasks: 3
  commits: 6
plan_head_before: 0dfe3f808e279291f2c96cda30a11489ece651f1
plan_head_after: 643d1fb1e94026a2891de81fbd100c234630b141

tech-stack:
  added: []
  patterns:
    - "Every leg/metric reports n measured plus INCOMPLETE counts by IncompleteReason; a missing timestamp or price is never imputed or zero-filled"
    - "Live normalizer sorts every input by an explicit total key (never journal_event_id alone) so output is input-order independent; payloads read via an allow-list (phase, identifier) inside try/except"
    - "Section digests re-pinned deliberately when the section shape changes (paper_lifecycle expected.json re-pinned in Task 2)"

key-files:
  created:
    - src/analytics/lifecycle.py
    - src/analytics/latency.py
    - tests/test_analytics_latency.py
    - tests/test_analytics_lifecycle.py
    - tests/fixtures/phase10/paper_lifecycle/
    - tests/fixtures/phase10/opportunity_skipped_expired/
    - tests/fixtures/phase10/live_lifecycle/
  modified:
    - tests/phase10_helpers.py

key-decisions:
  - "SIGNAL_TO_SEEN is always INCOMPLETE(NO_SEEN_TIMESTAMP); Approval.requested_at_utc is documented as a delivery-request PROXY, never a read receipt"
  - "Paper sections carry synthetic_lag_seconds (APPROVAL_DELAY_LAG_SECONDS imported, never redefined); other evidence kinds carry None"
  - "Live approved_at_utc is set only for APPROVED approvals; a SKIPPED/EXPIRED approval's acted_at is not an 'approval' so it never enters the approval legs"
  - "Entry deviation sign: positive = worse (LONG actual - intended, SHORT intended - actual); PAPER is INCOMPLETE(NOT_MEASURED_FOR_EVIDENCE) because PaperRecord carries no prices"
  - "ENTRY_EXPIRY payload is malformed (MALFORMED_ROW, never fatal) when not valid JSON, not an object, lacking a string phase, or naming an identifier different from the event entity_id"

patterns-established:
  - "Evidence kinds are never pooled: build_execution_quality raises AnalyticsInputError on mixed evidence"
  - "Join accounting (JoinAccount matched/unmatched) instead of silently dropping unjoinable live rows"

requirements-completed: [JRN-01]

coverage:
  - id: D1
    description: "Tracer: paper PaperRecord rows normalize to LifecycleRecords and yield a digest-stamped execution-quality section with six fixed-order legs, honest INCOMPLETE buckets and the synthetic-lag label"
    requirement: JRN-01
    verification:
      - kind: unit
        ref: "tests/test_analytics_latency.py#test_tracer_paper_lifecycle_to_section"
        status: pass
    human_judgment: false
  - id: D2
    description: "Fill %, expiry-without-fill rate and signed entry deviation per evidence kind; empty denominators are None, PAPER deviation is INCOMPLETE, backtest lifecycle normalizer maps entry_kind"
    requirement: JRN-01
    verification:
      - kind: unit
        ref: "tests/test_analytics_latency.py#test_backtest_fill_and_expiry_rates_and_deviation"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_latency.py#test_deviation_sign_long_worse_when_above_short_worse_when_below"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_lifecycle.py#test_opportunity_skipped_and_expired_rows_are_retained"
        status: pass
    human_judgment: false
  - id: D3
    description: "Live lifecycle normalization with join accounting, twin-safe ENTRY_EXPIRY handling, malformed-row rejection, order independence and no payload free-text passthrough"
    requirement: JRN-01
    verification:
      - kind: unit
        ref: "tests/test_analytics_lifecycle.py#test_live_lifecycle_fixture_records_joins_and_rejections"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_lifecycle.py#test_output_is_identical_when_inputs_are_shuffled"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_lifecycle.py#test_malformed_payloads_are_counted_never_fatal"
        status: pass
    human_judgment: false
  - id: D4
    description: "That the paper synthetic-lag label and the delivery-request PROXY wording are presented to the operator as such (not as measured latency / read receipt) in rendered reports"
    requirement: JRN-01
    verification: []
    human_judgment: true
    rationale: "The engine carries the labels (synthetic_lag_seconds, proxy field docstring, NO_SEEN_TIMESTAMP); the wording a reader sees is a report-rendering concern verified when the report plan renders E-1"

duration: 12min
completed: 2026-09-29
status: complete
---

# Phase 10 Plan 03: Execution-Quality Lifecycle and Latency Summary

**Per-signal LifecycleRecord normalizers (paper, backtest, live) plus a digest-stamped execution-quality section with six fixed-order latency legs, fill %, expiry-without-fill rate and signed entry deviation, where every missing input is an explicit INCOMPLETE bucket and never an imputed number.**

## Performance

- **Duration:** ~12 min (wall-clock from first to last task commit)
- **Completed:** 2026-09-29
- **Tasks:** 3 (1 tracer + 2 auto), all TDD with separate RED then GREEN commits
- **Files:** 2 source modules, 2 test modules, 3 fixture sets (plus a shared helper addition)

## Accomplishments

- Paper rows group by signal_id into USER_EXECUTED / OPPORTUNITY / SYSTEM_ONLY records; the constant paper approval time is flagged `synthetic_lag` and the section surfaces `synthetic_lag_seconds = 30` (imported constant, guarded by an AST test that it is never reassigned).
- Six latency legs in the UI-SPEC E-1 order. SIGNAL_TO_SEEN is always `INCOMPLETE(NO_SEEN_TIMESTAMP)`; delivery/approval/order/fill legs measure only when both timestamps exist; negative intervals are `NEGATIVE_INTERVAL`; backtest evidence is `NOT_MEASURED_FOR_EVIDENCE` on every leg.
- Fill %, expiry-without-fill rate (RateStat, pct None on empty denominator) and signed entry deviation in price and bps (DeviationStat) per evidence kind.
- Live normalizer: latest approval per signal, entry order by trade_plan_id, quantity-weighted fill price, first-fill time, only `post_cancel` ENTRY_EXPIRY twins joined by client_order_id count as expiry, join accounting for all four joins, MALFORMED_ROW counting, order-independent output.

## Task Commits

1. **Task 1 RED:** `cbfe83c` test(10-03): failing paper lifecycle execution-quality tracer tests
2. **Task 1 GREEN:** `d4972ad` feat(10-03): paper lifecycle normalizer and six-leg execution-quality section
3. **Task 2 RED:** `ffd68c4` test(10-03): failing rate, deviation, backtest and opportunity lifecycle tests
4. **Task 2 GREEN:** `2472e38` feat(10-03): fill %, expiry rate, signed entry deviation and backtest lifecycle normalizer
5. **Task 3 RED:** `04903c6` test(10-03): failing live lifecycle normalizer tests and fixture
6. **Task 3 GREEN:** `643d1fb` feat(10-03): live lifecycle normalizer with join accounting and ENTRY_EXPIRY handling

## Files Created/Modified

- `src/analytics/lifecycle.py` - LifecycleRecord, LifecyclePath, JoinAccount, LiveLifecycleResult and the three normalizers.
- `src/analytics/latency.py` - Leg, LegStat, RateStat, DeviationStat, ExecutionQualitySection, build_execution_quality.
- `tests/test_analytics_latency.py`, `tests/test_analytics_lifecycle.py` - tracer, rates, deviation, backtest, opportunity, live, shuffle, malformed and leak tests.
- `tests/fixtures/phase10/{paper_lifecycle,opportunity_skipped_expired,live_lifecycle}/` - hand-authored inputs and pinned expectations (paper section digest pinned).
- `tests/phase10_helpers.py` - added `make_paper_record` and `make_lifecycle_record` shared test builders.

## Decisions Made

See `key-decisions` above. The most consequential is that a live SKIPPED/EXPIRED approval does not populate `approved_at_utc`, so skip times never contaminate the DELIVERY_TO_APPROVED / SIGNAL_TO_APPROVED legs.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical] approved_at_utc restricted to APPROVED approvals**
- **Found during:** Task 3 design
- **Issue:** The plan text says `approved_at_utc = Approval.acted_at_utc`; a SKIPPED/EXPIRED approval also carries `acted_at_utc`, which would be mislabelled as an approval time and pollute the approval legs (fabricated measurement, T-10-07).
- **Fix:** Set `approved_at_utc` only when the result is APPROVED; SKIPPED/EXPIRED still carry `delivery_requested_at_utc` so SIGNAL_TO_DELIVERY is measured.
- **Files modified:** src/analytics/lifecycle.py
- **Commit:** 643d1fb

**2. [Rule 2 - Missing critical] Extra malformed-payload hardening**
- **Found during:** Task 3
- **Issue:** JournalEvent validates JSON at construction, so "not valid JSON" only reaches the normalizer via bypass; the realistic malformed shapes are valid JSON that is not an object, lacks a string `phase`, or names an `identifier` different from the event entity_id.
- **Fix:** All of these (and invalid JSON) count as MALFORMED_ROW; the fixture pins the missing-phase case, unit tests cover the rest.
- **Files modified:** src/analytics/lifecycle.py, tests/test_analytics_lifecycle.py
- **Commit:** 643d1fb

**3. [Rule 3 - Blocking] Shared test builders added to tests/phase10_helpers.py**
- **Issue:** Paper-record and lifecycle-record builders are needed by two test modules; the plan's file list did not include the helper module.
- **Fix:** Added the two builders there (no behavior change to existing helpers).
- **Commit:** ffd68c4

**4. [Rule 1 - Bug] Section digest re-pinned once**
- The paper_lifecycle `section_digest` was pinned at the end of Task 1 and deliberately re-pinned in Task 2 when RateStat/DeviationStat joined the section shape (same practice as plan 10-01).

**Total deviations:** 4 (2 missing-critical, 1 blocking, 1 deliberate re-pin). **Impact:** no scope creep; all strengthen the no-imputation guarantees.

## Issues Encountered

- A mypy strict error (loop variable `approval` reused with a different type) and one ruff import-order finding surfaced during Task 2/3 GREEN and were fixed before committing. The pre-existing `src/adapters/telegram_notify.py` mypy error is unchanged and out of scope. An accidental `ruff format` on the plan-10-01 file `src/analytics/stats.py` was reverted before any commit.

## Verification

- `pytest tests/test_analytics_latency.py tests/test_analytics_lifecycle.py tests/test_analytics_purity.py tests/test_analytics_typing.py tests/test_paper_attribution.py` plus the plan-10-01 analytics tests: all pass (constant `APPROVAL_DELAY_LAG_SECONDS` unchanged).
- `ruff check` on `src/analytics` and the two new test modules: clean. `mypy src/analytics`: clean (only the pre-existing telegram_notify error remains repo-wide).

## Known Stubs

None. No hardcoded empty values reach any rendering path; empty/None values are the explicit no-data representation by design.

## Threat Flags

None. No new network endpoints, auth paths, file access or schema changes; the live normalizer reads frozen dataclasses only and mitigates T-10-07/08/09 as specified.

## Next Phase Readiness

Ready for the approval-delay and report plans: `LifecycleRecord` and `ExecutionQualitySection` are the stable contracts; `LiveLifecycleResult.joins`/`rejected` are ready to render as the UI-SPEC "Unmatched joins" rows.

## Self-Check: PASSED
