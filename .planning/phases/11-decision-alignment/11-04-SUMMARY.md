---
phase: 11-decision-alignment
plan: 04
subsystem: operations-risk-docs
tags: [d031, d033, d034, d035, d036, d037, d038, d042, safe-mode, quantization, gate-module]
status: complete

requires:
  - phase: 11-decision-alignment
    provides: plans 11-01..11-03 gate-module pattern (scripts/decision_alignment) and the 11-02 baseline-v4 / working_type registry key
provides:
  - Entries-only SAFE_MODE with the D034 protective ladder in SECURITY_AND_OPERATIONS and RUNBOOK
  - D033 daily loss, D035 margin rules, D036-D038 cost wording, one canonical quantization statement and the extended constraint snapshot in RISK_MANAGEMENT
  - Persisted plan fields in DATA_MODEL, registry-key/cost guidance (new section 10) in CONFIGURATION, a valid alert example
  - scripts/decision_alignment/ops_risk.py gates OR-01..OR-10b (11 gates) plus 43 tests
affects: [11-05, 11-06, 11-07, 11-08, phase-17, phase-20, phase-21, phase-22]

requirements-completed: []

actuals:
  tokens: 12000
  tasks: 3
  commits: 3
plan_head_before: 3f9d00f961ac91966e93304f2d829547ad35be23
plan_head_after: fb02f8b0bf8d3a103cd13c254cb99a6bcf5ac2b1

tech-stack:
  added: []
  patterns:
    - "Gate module of pure text functions (normalise, section extract, required phrases, per-line forbidden regexes) plus run(); negative tests use git show 679825c"

key-files:
  created:
    - scripts/decision_alignment/ops_risk.py
    - tests/test_decision_alignment_ops_risk.py
  modified:
    - docs/operations/SECURITY_AND_OPERATIONS.md
    - docs/operations/RUNBOOK.md
    - docs/trading/RISK_MANAGEMENT.md
    - docs/data/DATA_MODEL.md
    - docs/configuration/CONFIGURATION.md
    - docs/trading/SIGNAL_AND_ALERTS.md

key-decisions:
  - "Liquidation buffer is documented only as a registry parameter whose value is chosen in Phase 22; a gate rejects any hard-coded number"
  - "Canonical quantization order lives on one labelled line 'Canonical order (D031):' and the gate checks token order on that line, not the whole section"
  - "OR-10 split into OR-10a (CONFIGURATION) and OR-10b (alert example), giving 11 gates"

requirements-completed-note: "RISK-02, OPS-01, EXEC-02 are also claimed by 11-05, 11-06 and 11-08 and were deliberately not marked complete here."

coverage:
  - id: D1
    description: "SAFE_MODE is entries-only with the D034 ladder in both operations documents; D042 secrets control and webhook pointer"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_decision_alignment_ops_risk.py (OR-01..OR-03 positive, pre-change and forbidden-line negative tests)"
        status: pass
    human_judgment: false
  - id: D2
    description: "RISK_MANAGEMENT states D033, D035, D036-D038, SL integrity, no averaging down, one canonical quantization order, extended snapshot"
    requirement: "RISK-02"
    verification:
      - kind: unit
        ref: "tests/test_decision_alignment_ops_risk.py (OR-04..OR-08, synonym, order swap, hard-coded buffer tests)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Persisted plan fields, registry key guidance and a minimum_rr-compliant alert example in Asia/Ho_Chi_Minh"
    requirement: "EXEC-02"
    verification:
      - kind: unit
        ref: "tests/test_decision_alignment_ops_risk.py (OR-09, OR-10a, OR-10b, arithmetic test)"
        status: pass
    human_judgment: false
---

# Phase 11 Plan 04: Operations and Risk Documents Alignment Summary

**SAFE_MODE is now entries-only with an automatic stop-loss ladder, RISK_MANAGEMENT carries the D033 UTC-day daily loss, D035 isolated-margin rules and a single canonical quantization order, and an 11-gate module fails if the stale wording returns.**

## Performance

- **Completed:** 2026-09-30
- **Tasks:** 3 (1 tracer, 2 auto/tdd)
- **Files:** 2 created, 6 modified; no `src/` file touched by this plan

## Accomplishments

- SECURITY_AND_OPERATIONS section 7 and RUNBOOK sections 2, 3, 4, 7, 9: new entry orders only are blocked; protective and reduce-only orders always allowed; missing or canceled SL is automatically re-placed at the original plan SL (never wider); a rejected or unacknowledged SL leads to a reduce-only market close then a HIGH alert; a DB failure must not block risk-reducing actions; a stop paired with a working ENTRY order is not an orphan (D034, F-401).
- Section 1 secrets wording is the D042 control (0600 `.env`, provider disk encryption; D045 exclusion pointer); webhook bullet points at TRADINGVIEW.md section 5 and says TradingView cannot sign (F-052); alert list adds daily-loss WARNING/DAILY_STOP.
- RISK_MANAGEMENT: taker entry fee and `partial_fill_fraction` 1.0 (D036, D038); daily loss placeholder replaced with 0.5%/1.0% and registry keys; section 8 defines the UTC day, loss formula, equity base and DAILY_STOP behavior (D033); section 9 ISOLATED / 5x / explicit marginType and leverage / liquidation beyond SL with a registry-parameter buffer / resting-entry margin check (D035); section 11 single line "Canonical order (D031)" matching `src/risk/quantization.py`, reason codes MIN_QTY_REJECT, NOTIONAL_REJECT, UTILIZATION_REJECT, synonym QUANTIZATION_REJECT removed from the document; section 12 snapshot extended and marked persisted per plan with a verify marker.
- DATA_MODEL `trade_plans` gains `constraint_snapshot_json`, `constraint_snapshot_hash`, `working_type`, `margin_type`, `leverage`, `equity_used`. CONFIGURATION gets the registry-key note and section 10. Alert example now TP1 105275, TP2 106625, R:R 2.0 / 4.0, valid until 23:00 Asia/Ho_Chi_Minh.
- `ops_risk.py`: gates OR-01..OR-09, OR-10a, OR-10b, all green on the real repo.

## Task Commits

1. Task 1 (tracer): `3946ac7` - SAFE_MODE ladder, secrets, webhook pointer, gates OR-01..OR-03
2. Task 2: `9131b7e` - RISK_MANAGEMENT D033/D035/D036-D038/D031, gates OR-04..OR-08
3. Task 3: `fb02f8b` - DATA_MODEL fields, CONFIGURATION section 10, alert example, gates OR-09..OR-10

## Verification

- `pytest tests/test_decision_alignment_ops_risk.py -q -p no:cacheprovider`: 43 passed.
- `ops_risk.run()` one-liner: 11 gates, 0 failed.
- `ruff check`, `ruff format --check` and `mypy` on the module: clean.
- Doc-reading suites (`test_domain_entities`, `test_drills`, `test_execution_health`, `test_risk_portfolio`, `test_risk_quantization`) green alongside the new tests.
- Full-repository `pytest -x` (run in the background after the Task 3 edits were in place): all dots, exit code 0.
- `git diff 679825c --stat -- src/` is not empty, but the only file is `src/domain/registry.py` from plan 11-02 commit 313384d; this plan changed nothing under `src/`.
- Alert arithmetic: zone midpoint 103925, risk 675 to SL 103250, TP1 leg 1350 gives R:R 2.0; TP2 = 103925 + 2 x 1350 = 106625 gives 4.0 (asserted in a test).

## Deviations from Plan

**1. [Rule 3 - Blocking] WebSocket citation could not be re-fetched**
- **Found during:** Task 1
- **Issue:** The read_first step says to fetch the Binance page before citing (D-14). The environment has no WebFetch tool and `curl` returned HTTP 202 with an empty body for the usds-margined-futures pages, so the 24-hour lifetime could not be confirmed.
- **Fix:** Cited the plan's verified usds-margined-futures URL (Important-WebSocket-Change-Notice) and reworded the claim to "believed to have a 24-hour lifetime" with an explicit "Verify ... against current Binance docs before implementation" marker, as the plan allows when unconfirmed.
- **Files modified:** docs/operations/SECURITY_AND_OPERATIONS.md
- **Commit:** 3946ac7

**2. [Ordering] OR-10 split** into OR-10a and OR-10b, which the plan explicitly permits.

**Total deviations:** 1 workaround (documented above), 1 permitted split. **Impact:** none on scope; the citation needs a re-check in plan 11-05, which owns exchange facts.

## Issues Encountered

- Windows file-write behavior: rewrites through Python `write_text` produce CRLF; the working tree is CRLF anyway (autocrlf) so commits are unaffected apart from git's LF/CRLF warnings.
- `git add` printed a gitignore hint for `docs/data`; `DATA_MODEL.md` is tracked and was staged and committed normally.

## Known Stubs

None. No placeholders were introduced; the liquidation buffer is intentionally a registry parameter to be valued in Phase 22 (D035 fixes no number).

## Threat Flags

None. T-11-10 (blocked protective orders), T-11-11 (secrets wording), T-11-12 (stale daily-loss/margin rules) are mitigated by gates OR-01, OR-02, OR-04 and OR-05.

## Next Phase Readiness

Ready for 11-05. Follow-ups outside this plan: D045 (application-level secret encryption exclusion) and the state-transition requirement land in plan 11-07; the TRADINGVIEW.md section 5 rewrite and the coin-futures link in SOURCES.md and ARCHITECTURE.md belong to a sibling plan; AGENTS.md / PROJECT.md / protocol pointers to the canonical quantization line belong to plans 11-01 and 11-06.

## Self-Check: PASSED

Files exist (ops_risk.py, test file, six amended documents); commits 3946ac7, 9131b7e, fb02f8b found in git log; verify commands re-run green.
