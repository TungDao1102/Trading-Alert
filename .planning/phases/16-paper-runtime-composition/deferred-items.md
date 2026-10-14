# Phase 16 deferred items

Out-of-scope findings logged by executors; not fixed in the plan that found them.

## Found during plan 16-15 (2026-10-09)

- `tests/test_cost_parity.py::test_simulator_and_paper_call_evaluate_risk_with_identical_arguments` fails with `{'open_positions': []} != {'open_positions': ()}` (the simulator passes a list, the paper loop a tuple to `evaluate_risk`). Plan 16-15 only created `src/paper/coverage.py` and two test files and touched no simulator, paper-loop or risk code, so the failure is not caused by it. Owner: whichever plan next touches `src/paper/loop.py` or `src/backtest/simulator.py` call arguments; the fix is to make both pass the same sequence type (decide which, without changing risk semantics).

## Tracker notes from the protocol v2.3.0 landing (2026-10-14)

- Plan 16-37 Task 1 (`16-37-PLAN.md` lines 72 and 74) reads and validates `docs/research/preregistration/research-run-1-grid.json`. That file does not exist: the registered grids are three files, one per family (`research-run-1-grid-trend-pullback.json`, `-breakout-retest.json`, `-range-mr.json`, 16 points each, 48 in total; the hypothesis file explains why, line 192). Task 1 has already run; the plan text is left as written and this note is the correction.
- Plan 16-46 grows from one run to six execution bindings (3 families x scenarios S0 and S1), each with its own manifest, grid and authorization (decisions/16-DEC-V230.md, D068). Only S0 serves confirmatory research; S1 (`research-run-1-constraints-S1.json`, evidence/16-37-s1-constraint-file.md) is descriptive on Development and Validation and never uses the Holdout.
- G3 (D069) needs a seeded one-sided stationary block-bootstrap p-value producer that does not exist in `src/`; `src/research/multiplicity.py` corrects supplied p-values only. CORRECTION (2026-10-14): plan 16-46 does NOT need it (16-46 prints no G3 figure, and G1 to G5 never rank candidates in Phase 16, L-10). The executable G1-G5 gate code belongs to Phase 26 (inherited item G3-004). The draft specification of the producer, with its open decisions, is `decisions/16-DRAFT-G3-pvalue-producer-spec.md`. Conventions already agreed: p-values as `Decimal`, 48 in total, p = 1 for a candidate without a closed Validation trade.
- `src/analytics/gates.py` G-cells still read PENDING_THRESHOLD_TBD (its own docstring); not changed by the landing.
