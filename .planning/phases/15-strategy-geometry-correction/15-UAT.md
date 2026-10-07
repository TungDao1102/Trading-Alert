---
status: complete
phase: 15-strategy-geometry-correction
source: 15-01-SUMMARY.md .. 15-15-SUMMARY.md, 15-VERIFICATION.md
started: 2026-10-07T00:00:00Z
updated: 2026-10-07T00:00:00Z
---

## Current Test

[testing complete — 2 issues recorded (G-15-10, G-15-11), gap-closure planning in progress]

Note: Phase 15 is a backend phase with no UI. At the user's request, Claude answered tests 1-8
from evidence it ran itself (not from the user's own observation), the same way Phase 14 did.
Tests 9-11 are decisions that only the user can make; Claude never picks them.
Evidence run 2026-10-07: 12 geometry/registry/doc test modules passed, one process per file;
`ruff check src tests scripts` clean; `mypy src` clean (149 files);
decision-alignment params gate PA-01..PA-08 all ok.

## Tests

### 1. Stop sits outside the whole entry zone
expected: A trend-pullback plan never has its stop inside the entry zone; otherwise it is rejected STOP_TOO_TIGHT. A signal bar already through the stop is rejected INVALIDATED. The stop is the outer zone edge minus the ATR buffer.
result: pass
source: automated (claude)
evidence: tests/test_planner_geometry.py (16), tests/test_geometry_property.py (25, SL-outside-zone property); verifier read src/core/planner.py `_geometry_rejection`

### 2. Pivots are confirmed only after the right-hand bars close
expected: A pivot counts only once R=3 later bars have closed (3h on 1H, 12h on 4H). The evaluated bar is never the pivot, and a prefix of the data gives the same pivots as the full data.
result: pass
source: automated (claude)
evidence: tests/test_core_pivots.py (17), tests/test_no_lookahead.py, tests/test_prefix_invariance.py

### 3. Minimum stop distance and TP1 side apply to every parameter set
expected: A stop closer than min_stop_atr x ATR is rejected (equality passes); TP1 on the loss side is rejected RR_TOO_LOW; legacy sets go through the same validator.
result: pass
source: automated (claude)
evidence: tests/test_planner_geometry.py, tests/test_core_planner.py, tests/test_core_strategy_geometry.py (7)

### 4. Families B and C follow their sheets, or the deviation is written down
expected: Family B uses the narrow S/R zone stop with a first retest and with-regime gate; Family C regime comes from confirmed 4H pivots with the middle target; every difference from a sheet is a recorded deviation.
result: pass
source: automated (claude)
evidence: tests/test_core_strategy_breakout_retest.py (30), tests/test_core_strategy_range_mr.py (36), tests/test_geometry_audit_doc.py (20); GEOMETRY_AUDIT has 20 rows (5 MATCH, 8 FIX, 7 DEVIATION) per the verifier

### 5. Every new parameter value carries a provenance label; PLACEHOLDER sets are refused for paper
expected: Each new value has STRUCTURAL, COST_GUARD, DECISION, EXPERIMENT or PLACEHOLDER with a reason. A set with a PLACEHOLDER or missing rationale is refused when a paper stream is pinned.
result: pass
source: automated (claude)
evidence: tests/test_rationale.py (34), tests/test_paper_freeze.py (10); live call `pin_stream_epoch` on trend-pullback baseline-v6 and baseline-v3 both raise UnrationalizedParameterSet
observation: the refusal also hits the legacy baseline-v3, because it has no rationale table. See test 11 about wiring.

### 6. Old parameter sets keep their hashes
expected: No existing parameter_set_hash moved; the five new files are the only additions under params/.
result: pass
source: automated (claude)
evidence: scripts.decision_alignment.params.run() PA-01..PA-08 all ok; tests/test_registry.py (23, includes WR-01 regression)

### 7. A misconfigured range-mr set cannot crash a backtest
expected: A range-mr set whose regime_filter_lookback is below pivot_right_bars + 1 is refused when loaded, not when evaluated.
result: pass
source: automated (claude)
evidence: review finding WR-01 fixed in e0593a6; two new tests in tests/test_registry.py

### 8. Research re-run readiness (smoke twice with equal digests, census zero violations)
expected: On real BTCUSDT data, the smoke backtest run twice gives the same digest, and the geometry census reports invariant_violations 0.
result: skipped
reason: needs the local data store and minutes of runtime; not re-run in this UAT. Evidence is the digests and census counts recorded in 15-15-SUMMARY.md and GEOMETRY_AUDIT.md, and tests/test_geometry_census.py (30) and tests/test_smoke_backtest_cli.py (16) pass.

### 9. TP1 inside the far half of the entry zone (D054 item g)
expected: The user decides whether a plan whose TP1 is on the profit side of the entry reference but inside the far half of the zone is kept, rejected or left open.
result: skipped
reason: "Deferred follow-up: hoãn" (user chose to keep current behavior and defer, after Claude's recommendation; the minimum-RR gate at the zone mid still applies)

### 10. Three -v4 override values (baseline-no-trade-v4 minimum_rr 100; baseline-simple-trend-v4 zone_tolerance_atr 1.0 and minimum_rr 0.5)
expected: The user confirms what these values are, and D054 states it.
result: issue
reported: "Là mốc đối chứng, ghi rõ"
severity: minor

### 11. Paper-stream gate (pin_stream_epoch) is called where a paper stream starts
expected: Starting a paper stream with a set that lacks rationale or has PLACEHOLDER values is refused.
result: issue
reported: "Nối ngay trong Phase 15"
severity: major

## Summary

total: 11
passed: 7
issues: 2
pending: 0
skipped: 2
blocked: 0

## Gaps

- gap_id: G-15-10
  truth: "The three -v4 override values are labelled as comparison reference points, not evidence-backed parameters, in D054 and the rationale tables"
  status: failed
  reason: "User reported: Là mốc đối chứng, ghi rõ"
  severity: minor
  test: 10
  root_cause: "The 15-08 checkpoint gave no recorded basis for these values, so D054 states no label for them"
  artifacts:
    - path: "docs/DECISIONS.md"
      issue: "D054 row does not say the three -v4 overrides are comparison reference points"
    - path: "params/trend-pullback/baseline-no-trade-v4.toml"
      issue: "hash-locked; its rationale is already inside the pinned file and must NOT be edited in place"
  missing:
    - "State the label in D054 only (docs change); do not edit a pinned params file. If a rationale basis must change, that needs a new set and a new hash, which the user must approve"
  debug_session: ""

- gap_id: G-15-11
  truth: "run_paper_tick or the paper-start path calls pin_stream_epoch, so a set without rationale or with PLACEHOLDER values is refused"
  status: failed
  reason: "User reported: Nối ngay trong Phase 15"
  severity: major
  test: 11
  root_cause: "pin_stream_epoch (src/paper/freeze.py) enforces the rationale gate but nothing under src/ calls it; run_paper_tick loads sets directly (review IN-01)"
  artifacts:
    - path: "src/paper/freeze.py"
      issue: "gate exists, no production caller"
    - path: "src/paper/loop.py"
      issue: "run_paper_tick loads any set without the gate"
  missing:
    - "Call the gate where a paper stream starts"
    - "Planner must handle: the Phase 7 parity fixture and the paper tests deliberately run baseline-v6 (PLACEHOLDER-heavy), and legacy sets such as baseline-v3 are also refused. Tests need the explicit allow_unrationalized flag in tests only, never in src/"
    - "Whether a legacy set without a rationale table should be refused is a safety decision for the user, not the planner"
  debug_session: ""

## Deferred Follow-Ups

- test: 9
  idea: "hoãn — revisit whether to reject a TP1 inside the far half of the entry zone after the research re-run (D054 item g)"
  deferred_at: 2026-10-07
