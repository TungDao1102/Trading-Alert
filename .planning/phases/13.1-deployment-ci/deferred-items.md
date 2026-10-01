# Phase 13.1 deferred items (out of scope for the plan that found them)

## Found in plan 13.1-04

- `tests/test_backfill_cli.py::test_cli_prints_depth_in_run_header` (and occasionally
  `test_funding_step_runs_per_symbol_within_bounds`) fail intermittently with `rc == 1`
  (about 1 run in 15 to 30). Reproduced on the pristine plan-03 head `c2c85b8` in a detached
  worktree (2 failures in 30 runs), so it predates the redaction work. Cause not investigated;
  `backfill_cli.main` returns 1 from its generic `except Exception` branch. Candidate for a
  Phase 13.1 hardening or test-stability plan before the CI workflow turns the suite into a gate.
