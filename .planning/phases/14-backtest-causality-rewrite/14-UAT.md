---
status: complete
phase: 14-backtest-causality-rewrite
source: 14-01-SUMMARY.md .. 14-16-SUMMARY.md
started: 2026-10-05T00:00:00Z
updated: 2026-10-05T00:00:00Z
---

## Current Test

[testing complete — 1 known minor issue recorded]

Note: Phase 14 is a backend phase with no UI. At the user's request, Claude answered the UAT
checkpoints from evidence it ran or read itself (not from the user's own observation).
Evidence run: 19 test modules, 424 passed; `ruff check` clean; `mypy src` clean;
`verify_decision_alignment.py all` ALL_PASS (after the code-review fixes, commits c7fa4c2..461477b).

## Tests

### 1. No fill on the signal bar; trade-through vs touch
expected: A limit order never fills on its own signal bar; it fills only on a later minute that trades through the level by at least one tick; a touch alone is not a fill.
result: pass
source: automated (claude)
evidence: goldens signal_bar_touch_no_fill, trade_through_vs_touch, gap_through_limit; tests/test_backtest_entry.py

### 2. Multi-bar exits (SL, TP1 then TP2, TP1 then SL, stop-first tie)
expected: Positions hold across bars and exit by mark-price triggers; when stop and target are both touched in one minute the stop wins.
result: pass
source: automated (claude)
evidence: goldens hold_to_sl, tp1_then_tp2, tp1_then_sl, stop_first_tie; tests/test_backtest_exits.py

### 3. Funding paid/received and fail-closed coverage
expected: Funding is booked once per settlement the position spans (paid or received); missing funding coverage stops the run unless the gap is explicitly allowed and recorded.
result: pass
source: automated (claude)
evidence: goldens funding_paid_received, funding_between_times; tests/test_backtest_funding.py

### 4. Signal expiry clock
expected: A limit fills before signal_expiry_hours; another expires after it; the boundary minute behaves per spec.
result: pass
source: automated (claude)
evidence: goldens g3_fill_before_expiry, g3_expire_after, expiry_before_fill; tests/test_backtest_expiry_clock.py

### 5. Determinism
expected: Re-running the same input gives byte-identical output; shuffled input rows give identical output; a prefix run equals the extended run (excluding END_OF_DATA).
result: pass
source: automated (claude)
evidence: tests/test_backtest_determinism.py, tests/test_domain_no_float.py

### 6. END_OF_DATA and mark-data holes
expected: An open position at data end closes END_OF_DATA, never dated before its own TP1; a hole in mark data falls back to the trade-price bar, flagged, with gap-through-stop priced at the bar open.
result: issue
reported: "Fixed in review (CR-01, WR-04, WR-09) but WR-09 is only partly fixed: holes in an hour where the symbol has no strategy bar are still not scanned and leave no coverage note."
severity: minor

### 7. Experiment record identity binding
expected: assemble refuses a run whose strategy version, parameter-set hash, cost-model hash, universe or dataset id does not match the record; reproduce with empty inputs raises.
result: pass
source: automated (claude)
evidence: review fixes CR-02 (1c15d56), WR-03 (3377bd0); tests/test_backtest_experiment.py

### 8. Protocol v2.0.0 amendment is consistent
expected: Protocol header, DECISIONS row (D052/D053) and DOC_STATUS all agree at v2.0.0 and the gate passes.
result: pass
source: automated (claude)
evidence: `verify_decision_alignment.py all` -> ALL_PASS; tests/test_decision_alignment_protocol.py, test_kill_gate_docs.py, test_research_gate_negative.py

### 9. Real-data smoke (BTCUSDT, 90 days)
expected: The smoke script runs the v2 simulator twice on real data with identical digests and exit code 0.
result: pass
source: recorded evidence (not re-run now)
evidence: 14-14-SUMMARY: 162 trades, digest 806c885e..., runs 384.6 s / 371.2 s, tracemalloc peak ~7.8 MB; CLI covered by tests/test_smoke_backtest_cli.py. RSS unavailable on Windows; constraints were today's values (plumbing evidence only).

### 10. TP1 fraction 0.5 (D-27) is the intended exit policy
expected: The user confirms that closing half the position at TP1 is the policy they want.
result: pass
source: user decision on record
evidence: 14-CONTEXT D-27 (RESOLVED by the user 2026-10-04: "dùng 0.5"); D052 states "the TP1 fraction 0.5 was chosen by the user on 2026-10-04"; constant TP1_QUANTITY_FRACTION = Decimal('0.5') in src/backtest/semantics.py, covered by SIMULATOR_SEMANTICS_VERSION 2.0.0.

## Summary

total: 10
passed: 9
issues: 1
pending: 0
skipped: 0
blocked: 0

## Gaps

- truth: "Mark-data holes are detected and flagged in every window, including hours with no strategy bar"
  status: failed
  reason: "Known partial fix of review finding WR-09: needs a new field on the plan state"
  severity: minor
  test: 6
  root_cause: "_first_missing_mark_open runs only for windows that end at the symbol's own strategy-bar close"
  artifacts:
    - path: "src/backtest/lifecycle.py"
      issue: "hole scan skipped when bar is None"
  missing:
    - "Scan or record a coverage note for skipped minutes when the window has no strategy bar"
  debug_session: ""
