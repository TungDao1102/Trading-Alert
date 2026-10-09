# Phase 16 deferred items

Out-of-scope findings logged by executors; not fixed in the plan that found them.

## Found during plan 16-15 (2026-10-09)

- `tests/test_cost_parity.py::test_simulator_and_paper_call_evaluate_risk_with_identical_arguments` fails with `{'open_positions': []} != {'open_positions': ()}` (the simulator passes a list, the paper loop a tuple to `evaluate_risk`). Plan 16-15 only created `src/paper/coverage.py` and two test files and touched no simulator, paper-loop or risk code, so the failure is not caused by it. Owner: whichever plan next touches `src/paper/loop.py` or `src/backtest/simulator.py` call arguments; the fix is to make both pass the same sequence type (decide which, without changing risk semantics).
