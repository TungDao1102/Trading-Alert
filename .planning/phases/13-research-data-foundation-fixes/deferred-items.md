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

## Found during 13-03 execution (2026-09-30)

- `.venv/Scripts/python -m mypy src/paper/supervisor.py` reports
  `src/adapters/telegram_notify.py:287: error: Incompatible types in assignment (expression has
  type "datetime", variable has type "Decimal")` (pulled in transitively). `src/paper/supervisor.py`
  itself is clean. Pre-existing, unrelated to 13-03; not touched.

## Resolved by 13-11 (2026-09-30)

- The RQ-01/RQ-04 decision-alignment failures listed under 13-01 are fixed: the requirements gate now maps OPS-06 to Phase 13.1 (drift introduced by commit 7ceede3). `verify_decision_alignment.py all` ends ALL_PASS all.

## Phase 13 close-out (2026-10-03): deferred on purpose

Each item has an owner and the reason it is not done inside Phase 13. Items the review found that were small and in scope (CR-01..CR-04, WR-01..WR-07, IN-01..IN-04, the telegram_notify mypy error, funding coverage in the sufficiency report) were fixed in Phase 13 and are listed in `13-REVIEW-FIX.md` and `13-13-SUMMARY.md`, not here.

| # | Item | Owner | Why not now |
|---|------|-------|-------------|
| 1 | Funding is stored one Parquet file per tick (about 50,000 files under `data/raw/data_class=funding`). Group by day or month. | Infra (Phase 13.1 or backlog) | Changes the on-disk layout that the backfill, the case-input builder and the backup all read; storage layout belongs with the backup work. |
| 2 | The host store `data/raw` is outside the project backup flow (backups cover the Docker volume `rawdata`), and the user has OneDrive sync turned off, so the backfilled history has no second copy. | Phase 13.1 (backup) | New backup scope. Interim manual step: archive `data/raw` with a checksum to another disk. The history can be refetched (about 3 hours); the live OI in the Docker volume cannot. |
| 3 | Legacy Parquet partitions with a different Decimal scale (for example DOGSUSDT, SOLUSDT, the older 12 months of 1m trade). Readers widen them losslessly. | Optional, when needed | `scripts/repair_parquet_scale.py` exists (dry-run by default, writes copies to a new root, never in place). Repairing is optional and needs free disk space and a user decision. |
| 4 | The first funding tick of HYPEUSDT carries `.006` ms (12:00:00.006). | Phase 14 | Only matters when funding is joined to bar times; handle in the Phase 14 funding join. |
| 5 | A day for which Binance really has no bars is requested again on every backfill run (one request per such day). Accepted trade-off of the CR-02 fix. | None | Documented behaviour, cheap. |
| 6a | `test_deploy_docs.py::test_refresh_pins_lookup_is_read_only_and_reports_moves` fails only on this Windows machine: Git for Windows' `bash.exe` puts `/mingw64/bin` and `/usr/bin` ahead of the test's PATH prefix, so the stub `curl` and `git` never run and the real ones reach the network. Fix in 13.1: call the stubs by absolute path or inject them through an env variable. Expected to pass on Linux CI. | Phase 13.1 | Deployment test infrastructure. |
| 6b | `test_docker_cutover.py` forty-five-minute test is docker-marked and was not run (no Docker was started). The unit-level equivalents in `tests/test_cutover.py` pass. Real cause unknown. | Phase 13.1 | Needs a Docker run. |

Fixed in Phase 13 instead of deferred: `test_ci_docker_job` (stale assertion, now `shellcheck -x -P SCRIPTDIR deploy/*.sh`, commit 1c317c4) and the `telegram_notify.py` mypy error (already clean at HEAD, `mypy src` passes on 132 files).
