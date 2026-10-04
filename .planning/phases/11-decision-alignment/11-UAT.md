---
status: complete
phase: 11-decision-alignment
source: [11-01-SUMMARY.md, 11-02-SUMMARY.md, 11-03-SUMMARY.md, 11-04-SUMMARY.md, 11-05-SUMMARY.md, 11-06-SUMMARY.md, 11-07-SUMMARY.md, 11-08-SUMMARY.md]
started: 2026-10-04T00:00:00Z
updated: 2026-10-04T00:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Research-gate freeze step is version-bound (11-01 D1)
expected: Freeze step fails on any witness disagreement, including half-frozen D029-only
result: pass
source: automated
coverage_id: 11-01-D1
verified: tests/test_research_gate_negative.py green in the Phase 11 test run (13 files, all passed, 0 failures).

### 2. Protocol v1.1.0 frozen consistently (11-01 D2)
expected: Header, D043 row and DOC_STATUS agree; kill-gate doc tests moved
result: pass
source: automated
coverage_id: 11-01-D2
verified: tests/test_kill_gate_docs.py and tests/test_kill_gate_clock.py green; RESEARCH_PROTOCOL.md changelog line v1.1.0 / D043 present.

### 3. Numeric pre-registration G1-G5, single-use holdout (11-01 D3)
expected: Thresholds, holdout marker, no human override, intact D030; gates PR-01..PR-10
result: pass
source: automated
coverage_id: 11-01-D3
verified: tests/test_decision_alignment_protocol.py green; verify_decision_alignment.py all prints PASS for PR gates.

### 4. Pre-registered numbers reachable at dataset depth (11-01 D4)
expected: 100/30 trade floors, N = 25, 40/40/20 split are coherent and consistent in the protocol
result: pass
verified: RESEARCH_PROTOCOL.md section G1 (line 221) states 100 pooled and 30 per fold across four Validation folds, N = 25 variant budget (line 219), 40/40/20 split in the v1.1.0 changelog (line 400); mutually consistent and machine-checked by PR gates. Actual reachability at real data depth cannot be known until the Phase 14+ dataset exists, so this judgment is a document-consistency pass only.

### 5. Aligned parameter sets carry D036-D038 values (11-02 D1)
expected: Five sets with taker fee 0.0005, partial_fill_fraction 1, MARK_PRICE, v3.0.0
result: pass
source: automated
coverage_id: 11-02-D1
verified: tests/test_registry.py and tests/test_decision_alignment_params.py green.

### 6. Old parameter sets provably untouched (11-02 D2)
expected: Ten LF-normalised digests and parameter_set_hash values locked
result: pass
source: automated
coverage_id: 11-02-D2
verified: test_pre_phase_11_hashes_and_versions_are_unchanged green.

### 7. Registry gate re-hash for all 15 sets (11-02 D3)
expected: Re-hash green, working_type closed-set validation
result: pass
source: automated
coverage_id: 11-02-D3
verified: test_every_params_toml_has_a_pin_that_verifies green.

### 8. Universe manifest DRAFT validates (11-03 D1)
expected: D039 rule, 12 slots, gates UN-01..UN-05 ok
result: pass
source: automated
coverage_id: 11-03-D1
verified: tests/test_decision_alignment_universe.py green; UN gates PASS in the verify script.

### 9. Malformed manifests rejected; hash stable (11-03 D2)
expected: Every malformed variant rejected; hash order-independent, payload-sensitive
result: pass
source: automated
coverage_id: 11-03-D2
verified: universe rejection and hash tests green.

### 10. Manifest invisible to scanners; CLI exit codes (11-03 D3)
expected: Not seen by family scanners or tripwires; params/universe absent
result: pass
source: automated
coverage_id: 11-03-D3
verified: universe tests plus tests/test_kill_gate_registration.py and tests/test_analytics_files.py green in the full suite (no failures there).

### 11. SAFE_MODE entries-only, D034 ladder, D042 (11-04 D1)
expected: Both operations docs state it; secrets control and webhook pointer
result: pass
source: automated
coverage_id: 11-04-D1
verified: tests/test_decision_alignment_ops_risk.py green (OR-01..OR-03).

### 12. RISK_MANAGEMENT decisions D033-D038, one quantization order (11-04 D2)
expected: All stated, canonical order, extended snapshot
result: pass
source: automated
coverage_id: 11-04-D2
verified: OR-04..OR-08 green.

### 13. Persisted plan fields and Asia/Ho_Chi_Minh alert example (11-04 D3)
expected: Fields, registry key guidance, minimum_rr-compliant example
result: pass
source: automated
coverage_id: 11-04-D3
verified: OR-09, OR-10a, OR-10b green.

### 14. 200 conditional-order limit account-wide (11-05 D1)
expected: Dated citation and verify marker in EXECUTION_SPEC
result: pass
source: automated
coverage_id: 11-05-D1
verified: tests/test_decision_alignment_exchange.py EX-01 green.

### 15. Algo trigger-time semantics and D034 wording (11-05 D2)
expected: FINISHED is not filled; REJECTED/EXPIRED at trigger; reason in o.rm
result: pass
source: automated
coverage_id: 11-05-D2
verified: EX-02..EX-05 green. Note: the exact ALGO_UPDATE wording and the 24h WS lifetime still need browser re-confirmation against live Binance docs before Phase 18 (see test 22).

### 16. BINANCE.md claims and source register (11-05 D3)
expected: WS split, workingType default, MARKET_LOT_SIZE / PERCENT_PRICE, unverified audit claims flagged; no coin-futures citation
result: pass
verified: docs/integration/BINANCE.md line 60 (workingType MARK_PRICE explicit, default CONTRACT_PRICE not relied on), line 79 (MARKET_LOT_SIZE, PERCENT_PRICE), line 81 (audit claims labelled unverified); EX-06, EX-06a, EX-07, EX-08 green in the Phase 11 test run.

### 17. No HMAC claim for TradingView; real scheme documented (11-06 D1)
expected: TRADINGVIEW section 5 with F-052 marker
result: pass
source: automated
coverage_id: 11-06-D1
verified: tests/test_decision_alignment_authority.py AU-01, AU-02 green.

### 18. Generated AGENTS.md equals sources (11-06 D2)
expected: FastAPI row and Quantization bullet match STACK.md / PROJECT.md
result: pass
source: automated
coverage_id: 11-06-D2
verified: AU-03, AU-05 green.

### 19. One quantization order across four locations (11-06 D3)
expected: RISK_MANAGEMENT s11, protocol s2, PROJECT.md, AGENTS.md agree
result: pass
source: automated
coverage_id: 11-06-D3
verified: AU-04, AU-06 green.

### 20. GLOSSARY canonical codes (11-07 D1)
expected: One canonical code per concept; section 10 ApprovalResult
result: pass
source: automated
coverage_id: 11-07-D1
verified: tests/test_decision_alignment_bookkeeping.py GL-01..GL-06 green.

### 21. 13 lost MUST requirements registered (11-07 D2)
expected: Traceability and ROADMAP lines, all Pending
result: pass
source: automated
coverage_id: 11-07-D2
verified: RQ-01..RQ-05 green.

### 22. D044/D045 and DOC_STATUS log (11-07 D3)
expected: Appended contiguously with owners and exclusions
result: pass
source: automated
coverage_id: 11-07-D3
verified: DC-01..DC-06 green.

### 23. Canonical vocabulary and ApprovalResult value set intended (11-07 D4)
expected: Collapsed canonical/alias split and PENDING/APPROVED/SKIPPED/EXPIRED are the intended vocabulary
result: pass
verified: docs/GLOSSARY.md section 10 lists exactly PENDING, APPROVED, SKIPPED, EXPIRED and maps ApprovalAction via action_to_result (APPROVE -> APPROVED; SKIP_USER, SKIP_BUSY, CANCEL -> SKIPPED; SIMULATE -> PENDING); GL tests confirm union equals the 23-member enum and every code src/ references is canonical.

### 24. Single read-only verify command (11-08 D1)
expected: PASS/FAIL lines, exit 0/1/2, gate-count guard, read-only
result: pass
verified: `uv run python scripts/verify_decision_alignment.py all` ends `ALL_PASS all`, exit 0, 65 lines starting PASS (summary recorded 64 plus the aggregate line); tests/test_decision_alignment.py green incl. injected-fake and read-only tests.

### 25. registry-gate CI runs the alignment checks (11-08 D2)
expected: Workflow runs verify script and freeze/clock/negative/alignment tests
result: pass
source: automated
coverage_id: 11-08-D2
verified: four static workflow tests in tests/test_decision_alignment.py green.

### 26. Full suite green after Phase 11 (11-08 D3)
expected: Whole suite green; no fixture/pin/golden regenerated
result: issue
reported: "Full run `uv run pytest tests -q` (TEST_DATABASE_URL set) shows 2 failures, both outside Phase 11 files: tests/test_deploy_docs.py::test_refresh_pins_lookup_is_read_only_and_reports_moves and tests/test_docker_cutover.py::test_the_reported_oi_gap_is_the_engineered_forty_five_minutes (assert 3 == 0). All 13 Phase 11 test files pass."
severity: minor

### 27. ALGO_UPDATE wording and 24h WS lifetime vs live Binance docs
expected: Documented wording matches current official Binance documentation
result: skipped
reason: needs browser re-confirmation against live Binance docs before Phase 18; not possible read-only offline

## Summary

total: 27
passed: 25
issues: 1
pending: 0
skipped: 1
blocked: 0

## Gaps

- truth: "Full test suite is green after all Phase 11 changes (11-08 D3)"
  status: failed
  reason: "Agent-run: 2 failures in full suite, test_deploy_docs refresh-pins read-only test (the pin lookup output shows an unchanged/moved report; likely depends on network or tool state) and test_docker_cutover OI-gap test (subprocess returned 3, expected 0; likely depends on Docker/environment). Neither touches Phase 11 files; Phase 11 changes are not implicated but not proven independent of environment."
  severity: minor
  test: 26
  root_cause: ""
  artifacts: []
  missing: []
  debug_session: ""
