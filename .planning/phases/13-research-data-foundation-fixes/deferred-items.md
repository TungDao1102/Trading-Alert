# Phase 13 deferred items (out-of-scope discoveries)

## Found during 13-01 execution (2026-09-30)

- `tests/test_decision_alignment.py::test_all_mode_passes_on_real_repository`,
  `::test_each_mode_passes_on_real_repository[reqs]`, `::test_run_is_read_only`, and
  `tests/test_decision_alignment_bookkeeping.py::test_requirement_gates_pass_on_real_repo`,
  `::test_thirteen_new_ids_are_registered_and_mapped`,
  `::test_completed_new_requirement_does_not_fail_rq01`,
  `::test_run_returns_seventeen_passing_gates` fail on the real repository with
  `FAIL RQ-01 :: OPS-06 row is Phase 13.1, expected Phase 13` and
  `FAIL RQ-04 :: Phase 13 Requirements line lacks OPS-06`.
  Cause: the planning docs moved OPS-06 to Phase 13.1 while the decision-alignment gate still
  expects it under Phase 13. Unrelated to 13-01 (no `.planning/` requirement text or
  `scripts/decision_alignment` file was touched). Owner: whoever reconciles ROADMAP/REQUIREMENTS
  with the decision-alignment gate (likely Phase 13.1 planning).
