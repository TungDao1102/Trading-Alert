---
phase: 10-journal-depth-kill-gate-operations
plan: 06
subsystem: analytics
tags: [analytics, approval-delay, live-outcomes, net-pnl, exchange-semantics, fail-closed, decimal, determinism, golden-fixtures, tdd]

requires:
  - phase: 10-journal-depth-kill-gate-operations
    provides: "10-01 analytics core (EvidenceKind, IncompleteReason, TradeOutcome, Estimate/DistStat, stats helpers, purity/typing guards)"
  - phase: 10-journal-depth-kill-gate-operations
    provides: "10-03 LifecycleRecord/LifecyclePath normalizers (paper/backtest/live) and the execution-quality section conventions"
  - phase: 07-paper-trading
    provides: "APPROVAL_DELAY_LAG_SECONDS synthetic paper approval-delay constant (imported, never modified)"
provides:
  - "build_approval_delay: three side-by-side METRICS section 3 reports (System / User execution / Opportunity) with descriptive-only blocks, INCOMPLETE reasons and the SYNTHETIC LAG label for PAPER"
  - "delay_bucket_for + DelayBucketRow: LIVE-only signal->approve buckets (<1m, 1-5m, 5-30m, >=30m) plus measured_delay calibration distribution"
  - "normalize_live_outcomes: Signal/TradePlan/Order/Fill -> LIVE TradeOutcome with explicit net-PnL rules behind the fail-closed LIVE_NET_PNL_SEMANTICS_VERIFIED gate"
affects: [10-07, 10-08, 10-09, 10-10, 10-11, 10-12]

actuals:
  tokens: 17200
  tasks: 3
  commits: 7
plan_head_before: d63da8c03d217c67ecab8014659f895b9976e02d
plan_head_after: faf5dffeaa9ea19c941d92c9e455b518ca23427f

tech-stack:
  added: []
  patterns:
    - "Report blocks are descriptive only: no delta/rank/best field exists on any approval-delay dataclass, guarded by a field-name test (D-02)"
    - "Exchange-sensitive semantics sit behind a module-level fail-closed constant whose docstring records the verification attempt (URL, date, result); tests cover both branches by monkeypatching the constant"
    - "Fixture directories hold one input/expected pair with cases nested under keys (paper/live, verified_true/verified_false)"

key-files:
  created:
    - src/analytics/approval_delay.py
    - src/analytics/live_outcomes.py
    - tests/test_analytics_approval_delay.py
    - tests/test_analytics_live_outcomes.py
    - tests/fixtures/phase10/approval_delay_three_reports/
    - tests/fixtures/phase10/live_net_r/
  modified: []

key-decisions:
  - "LIVE_NET_PNL_SEMANTICS_VERIFIED stays False: the official Binance Account-Trade-List page is a client-rendered shell (empty body / HTTP 202 challenge) and no accessible source states whether realizedPnl is gross or net of commission, so live R is INCOMPLETE(UNVERIFIED_EXCHANGE_SEMANTICS) until a human records a docs citation"
  - "Net PnL = sum(fill.realized_pnl) - sum(fill.commission), only when every commission asset is USDT; non-quote commission is INCOMPLETE(COMMISSION_ASSET_NOT_QUOTE) with no conversion; funding is excluded and stated"
  - "System-report R is realized-else-hypothetical; opportunity-report R is hypothetical only; a missing hypothetical is INCOMPLETE(NO_HYPOTHETICAL_OUTCOME), never imputed"
  - "Records are ordered by (detection time, undated last, signal key) rather than by signal key alone so the stationary block bootstrap sees a time-adjacent series (a total order, deterministic)"
  - "Delay buckets and measured_delay are computed for LIVE evidence only; negative delays (NEGATIVE_INTERVAL) and approvals without a signal time (UNMATCHED_JOIN) are counted in the section's delay_incomplete, never bucketed"

patterns-established:
  - "Every section takes exactly one EvidenceKind and raises AnalyticsInputError on mixed evidence or duplicate signal keys"
  - "Live normalizer output is independent of input order (explicit total sort keys), verified by shuffled-input tests"

requirements-completed: [JRN-01]

coverage:
  - id: D1
    description: "Tracer: System / User execution / Opportunity reports for PAPER evidence side by side with honest INCOMPLETE reasons, hypothetical_used flags and the SYNTHETIC LAG (APPROVAL_DELAY_LAG_SECONDS=30) label built from the imported constant"
    requirement: JRN-01
    verification:
      - kind: unit
        ref: "tests/test_analytics_approval_delay.py#test_tracer_three_reports_paper"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_approval_delay.py#test_synthetic_lag_label_uses_imported_constant"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_approval_delay.py#test_missing_hypothetical_is_never_imputed"
        status: pass
    human_judgment: false
  - id: D2
    description: "LIVE-only signal->approve delay buckets in fixed order with exact Decimal edges, measured-delay calibration distribution, PAPER/BACKTEST empty buckets, paper constant unchanged"
    requirement: JRN-01
    verification:
      - kind: unit
        ref: "tests/test_analytics_approval_delay.py#test_delay_bucket_boundaries"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_approval_delay.py#test_live_buckets_counts_and_fixed_order"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_approval_delay.py#test_paper_evidence_has_no_buckets_and_keeps_synthetic_label"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_approval_delay.py#test_paper_constant_is_unchanged"
        status: pass
    human_judgment: false
  - id: D3
    description: "Live-row normalizer: VWAP entry/exit, exit kind, open-position detection, explicit net-PnL rule, USDT-only commission, both branches of the exchange-semantics gate pinned"
    requirement: JRN-01
    verification:
      - kind: unit
        ref: "tests/test_analytics_live_outcomes.py#test_verified_semantics_branch_gives_net_r"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_live_outcomes.py#test_unverified_semantics_branch_is_fail_closed"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_live_outcomes.py#test_non_quote_commission_asset_yields_no_converted_number"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_live_outcomes.py#test_output_is_identical_when_inputs_are_shuffled"
        status: pass
    human_judgment: false
  - id: D4
    description: "That Binance realizedPnl excludes commission and commission is denominated in commissionAsset (the premise of the net-PnL rule); until confirmed against the official docs live R stays INCOMPLETE"
    requirement: JRN-01
    verification: []
    human_judgment: true
    rationale: "The official docs page could not be read programmatically (client-rendered, WAF challenge). A human must read the Account Trade List page (or confirm on a real fill), record the citation in the live_outcomes docstring and only then flip LIVE_NET_PNL_SEMANTICS_VERIFIED to True; both branches are already tested"

duration: 11min
completed: 2026-09-29
status: complete
---

# Phase 10 Plan 06: Approval-Delay Impact and Live Net-R Normalizer Summary

**Three side-by-side approval-delay reports (System / User execution / Opportunity) with LIVE-only signal-to-approve buckets and a synthetic-lag-labelled PAPER view, plus a live-row normalizer that computes net R under an explicit USDT-only PnL rule behind a fail-closed exchange-semantics gate that currently (verification not possible) renders live R as INCOMPLETE.**

## Performance

- **Duration:** ~11 min (wall-clock 06:48Z to 06:59Z)
- **Completed:** 2026-09-29
- **Tasks:** 3 (1 tracer + 2 auto), all with separate RED then GREEN commits
- **Files:** 2 source modules, 2 test modules, 2 fixture sets

## Accomplishments

- `build_approval_delay` produces three blocks over one metric block shape (n signals, n R-valued, mean R with bootstrap interval or explicit absence, win rate, expectancy, INCOMPLETE reason counts, `hypothetical_used`). Nothing ranks or subtracts blocks; a test asserts no field name implies comparison or advice.
- Opportunity R exists only when a hypothetical outcome is explicitly supplied; the fixture shows `NO_HYPOTHETICAL_OUTCOME` counted in both the System and Opportunity blocks. PAPER records without R are `NO_PAPER_OUTCOME`; LIVE without R are `OPEN_POSITION` (fill time present) or `NO_FILL_EVENT`.
- LIVE sections return exactly four `DelayBucketRow`s in the fixed order even when a bucket is empty; boundaries 59.999999 / 60 / 299 / 300 / 1799 / 1800 s land in the pinned buckets (counts 1 / 2 / 2 / 1 in the fixture). `measured_delay` (n 6, median 299.5, min 30, max 1800) is calibration evidence only. PAPER keeps `synthetic_lag_label` and never buckets; `APPROVAL_DELAY_LAG_SECONDS` is imported (AST-tested never assigned) and its definition in `src/paper/attribution.py` is asserted unchanged.
- `normalize_live_outcomes` builds entry/exit VWAP, exit kind (SL / TP1 / TP2 from the latest exit fill), open-position detection (exit quantity below entry quantity), and, when semantics are verified, net PnL 6.70 and R 0.67 for the fixture plan. A BNB commission gives `COMMISSION_ASSET_NOT_QUOTE` with no converted number; a non-positive risk budget gives `NO_RISK_VALUE`; a plan with no known signal gives `UNMATCHED_JOIN`; a non-positive fill quantity fails closed as `MALFORMED_ROW`.

## Exchange-semantics verification (assumption A7 / threat T-10-17)

Attempted on 2026-09-29 against https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Account-Trade-List. The page is a client-rendered shell (HTTP 200 with no field text; a URL with a query string returned an empty HTTP 202 challenge) and the legacy `binance-docs.github.io` site only redirects to it. The installed official SDK describes the fields only as "Realized Pnl." and "Commission."; a third-party docs mirror defines `commission` and `commissionAsset` but is silent on whether `realizedPnl` is gross or net of commission. Result: NOT VERIFIED, so `LIVE_NET_PNL_SEMANTICS_VERIFIED = False` (the plan explicitly accepts this outcome). Live R is INCOMPLETE(UNVERIFIED_EXCHANGE_SEMANTICS) in every report that consumes this normalizer until a human records a docs citation and flips the flag. The attempt, the finding and the open condition are in the module docstring and `LIVE_NET_PNL_SEMANTICS_NOTE`.

## Task Commits

1. **Task 1 RED:** `3e69811` test(10-06): failing three-report approval-delay tracer tests
2. **Task 1 GREEN:** `c5c8801` feat(10-06): three-report approval-delay section with synthetic-lag label
3. **Task 2 RED:** `fc72980` test(10-06): failing LIVE delay-bucket and measured-delay tests
4. **Task 2 GREEN:** `29a8374` feat(10-06): LIVE-only signal-to-approve delay buckets and measured-delay evidence
5. **Task 3 RED:** `3171fb4` test(10-06): failing live-row net-R normalizer tests and fixture
6. **Task 3 GREEN:** `942ccd8` feat(10-06): live-row normalizer with explicit net-PnL rules and fail-closed semantics gate
7. **Formatting:** `faf5dff` style(10-06): ruff-format live outcomes tests

Tracer gate: after Task 1 the tracer `<verify>` was re-run end-to-end (automated-only, `end-of-phase` mode) and passed before expansion.

## Files Created/Modified

- `src/analytics/approval_delay.py` - ReportLabel, ApprovalDelayBlock, DelayBucket, DelayBucketRow, ApprovalDelaySection, SYNTHETIC_LAG_LABEL, delay_bucket_for, build_approval_delay.
- `src/analytics/live_outcomes.py` - QUOTE_ASSET, LIVE_NET_PNL_SEMANTICS_VERIFIED, LIVE_NET_PNL_SEMANTICS_NOTE, LiveOutcomeResult, normalize_live_outcomes.
- `tests/test_analytics_approval_delay.py`, `tests/test_analytics_live_outcomes.py` - tracer, bucket boundaries, LIVE fixture, evidence-kind guards, both semantics branches, shuffle independence.
- `tests/fixtures/phase10/approval_delay_three_reports/` (cases `paper`, `live`) and `tests/fixtures/phase10/live_net_r/` (cases `verified_true`, `verified_false`) with pinned digests.

## Decisions Made

See `key-decisions` above. Also: BACKTEST evidence yields no label and no buckets; a BACKTEST record without R is `NO_FILL_EVENT` when the entry did not fill, else `NOT_MEASURED_FOR_EVIDENCE`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Correctness] Record ordering by detection time instead of by signal key alone**
- **Found during:** Task 1
- **Issue:** The plan says to sort records by signal key. `estimate_mean` requires values in stable time order (the stationary block bootstrap preserves adjacency); signal ids are content hashes, so key order would silently destroy adjacency and make the interval meaningless.
- **Fix:** Sort by (detection time, undated last, signal key), still a deterministic total order; the digest is input-order independent (tested).
- **Files modified:** src/analytics/approval_delay.py
- **Commit:** c5c8801

**2. [Rule 3 - Blocking] Official Binance docs not readable, so the verification step could not complete**
- **Found during:** Task 3
- **Issue:** developers.binance.com renders client-side (empty body / WAF 202); no fetch tool was available beyond curl and Context7.
- **Fix:** Followed the plan's fail-closed branch: flag False, attempt recorded in docstring and here. Not a code defect.
- **Files modified:** src/analytics/live_outcomes.py
- **Commit:** 942ccd8

**3. Additions beyond the plan text (no behavior conflict):** a `ReportLabel` enum, a section-level `delay_incomplete` tuple (where NEGATIVE_INTERVAL / UNMATCHED_JOIN delay exclusions are counted), and a trailing `style` commit for formatting the RED test file.

**Total deviations:** 2 auto-fixed (1 Rule 2, 1 Rule 3) plus additive fields. **Impact:** none on plan intent; the section digest of Task 1 was re-pinned in Task 2 because `delay_incomplete` and bucket fields joined the digest.

## TDD Gate Compliance

RED commits precede each GREEN commit. As in earlier Phase 10 plans, RED tests fail at import/collection (the module under test does not exist yet) rather than on an assertion; digest pins were finalized in the GREEN commit after every numeric assertion passed.

## Known Stubs

None. The unverified exchange-semantics gate is an intentional, documented fail-closed state (see above), not a stub.

## Threat Flags

None. No new network endpoints, auth paths, file access or schema changes were introduced (pure analytics modules).

## Issues Encountered

- Bash tool rejected heredocs containing apostrophes/triple quotes; edits were made with the Edit/Write tools instead (no effect on the result).

## Verification

- `uv run --python 3.13 pytest tests/test_analytics_approval_delay.py tests/test_analytics_live_outcomes.py tests/test_analytics_lifecycle.py tests/test_analytics_purity.py tests/test_analytics_typing.py tests/test_paper_attribution.py -q` passes (86 tests).
- `ruff check src/analytics tests/test_analytics_approval_delay.py tests/test_analytics_live_outcomes.py` passes; new files are ruff-format clean; `mypy src/analytics` is clean (the single pre-existing telegram_notify error is unrelated).

## Next Phase Readiness

Ready for 10-07. Downstream renderers must show live R as INCOMPLETE (UNVERIFIED_EXCHANGE_SEMANTICS) while `LIVE_NET_PNL_SEMANTICS_VERIFIED` is False, and must surface the SYNTHETIC LAG label for PAPER approval-delay sections. A human should confirm the Binance realizedPnl/commission semantics (coverage D4) before live R is relied on.

## Self-Check: PASSED

Created files verified on disk; the seven commits listed above exist in `git log`.
