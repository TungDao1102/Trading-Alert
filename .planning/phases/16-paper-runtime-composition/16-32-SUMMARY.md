---
phase: 16-paper-runtime-composition
plan: 32
subsystem: infra
tags: [docker-compose, soak, paper-runtime, healthcheck, restart-policy, bash, env-template]

requires:
  - phase: 16-paper-runtime-composition
    provides: "python -m src.paper.runtime with --hold-on-refusal, --healthcheck and REFUSAL_CODES (plans 16-22 and 16-26)"
provides:
  - "paper compose service running the runtime with a real exec-form probe, restart on-failure and the refusal hold"
  - "deploy/compose-soak.sh: compose wrapper pinned to project trading-soak that refuses down with -v or --volumes"
  - "deploy/soak.env.example: variable names only, no BINANCE_ name"
  - "tests/test_soak_compose.py: static, compose-config, template, guard and repository-scan tests"
affects: [16-33 soak runbook and pinned image, 16-40 host deployment, 16-29 restart safety]

actuals:
  tokens: 9800
  tasks: 3
  commits: 7
plan_head_before: 0f83db1dec3a968b43b70ad7f0946ffb38b82c8c
plan_head_after: 4ebdc2ba2b22b069ac5c8c94fc5418fedf95ba8c

tech-stack:
  added: []
  patterns:
    - "Static reading of docker-compose.yml with text slicing (the project has no YAML library) plus one compose-CLI render test"
    - "Shell wrapper structured as predicate functions plus main, runnable or sourceable, so the guard has a negative control"

key-files:
  created:
    - deploy/compose-soak.sh
    - deploy/soak.env.example
    - tests/test_soak_compose.py
  modified:
    - docker-compose.yml
    - tests/test_deploy_compose.py
    - docs/operations/DEPLOY_GUIDE.vi.md

key-decisions:
  - "Restart policy on-failure with no cap, plus --hold-on-refusal in the command (as planned): a refusal holds the container up and unhealthy instead of exiting"
  - "Probe interval 60s, timeout 15s, start period 6m, retries 3 copied from the collector (a test compares them)"
  - "The template lists the ALLOWED_ENV_NAMES, every BACKUP_ name of .env.example and IMAGE_TAG; OI_POLL_INTERVAL_SECONDS and OFF_HOST_BACKUP_TARGET are left out because no source file reads them"
  - "The wrapper refuses a -p or --project-name naming any project other than trading-soak, so it cannot be pointed at the development stack"

patterns-established:
  - "Restart-loop guard: restart_loop_problems(command, probe, restart) checked against the real service and a seeded one"

requirements-completed: []

coverage:
  - id: D1
    description: "paper service runs src.paper.runtime --hold-on-refusal with the --healthcheck probe, restart on-failure, logs volume, no ports"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_soak_compose.py#test_paper_service_runs_the_runtime_with_its_probe"
        status: pass
      - kind: integration
        ref: "tests/test_soak_compose.py#test_soak_project_renders_with_its_own_volume_names"
        status: pass
    human_judgment: false
  - id: D2
    description: "soak project trading-soak renders with its own volume names"
    verification:
      - kind: integration
        ref: "tests/test_soak_compose.py#test_soak_project_renders_with_its_own_volume_names"
        status: pass
    human_judgment: false
  - id: D3
    description: "soak environment template with names only and no trade-capable name"
    verification:
      - kind: unit
        ref: "tests/test_soak_compose.py#test_soak_template_has_names_only_and_no_binance_name"
        status: pass
    human_judgment: false
  - id: D4
    description: "wrapper refuses down -v and down --volumes however the project is named; repository scan finds no unguarded use"
    verification:
      - kind: unit
        ref: "tests/test_soak_compose.py#test_wrapper_refuses_down_with_volumes"
        status: pass
      - kind: unit
        ref: "tests/test_soak_compose.py#test_runbook_and_deploy_scripts_hold_no_unguarded_down_with_volumes"
        status: pass
    human_judgment: false

duration: 45min
completed: 2026-10-10
status: complete
---

# Phase 16 Plan 32: Soak deployment configuration Summary

**Compose `paper` service now runs `python -m src.paper.runtime --hold-on-refusal` with the real `--healthcheck` probe, and a `deploy/compose-soak.sh` wrapper pins every call to project `trading-soak` and refuses `down -v`, with a names-only env template that carries no trade-capable variable.**

## Performance

- **Duration:** about 45 min
- **Started:** 2026-10-10 (execution on the main tree)
- **Completed:** 2026-10-10T11:14Z
- **Tasks:** 3 (one tracer, two auto, all TDD)
- **Files modified:** 6 (3 created, 3 modified)

## Accomplishments

- The placeholder paper service is replaced: runtime command with the refusal hold, exec-form probe with the collector's timing, `on-failure` restart, `logs` volume, `db-upgrade` dependency, no ports or bind mounts; the comment names refusal codes 3 to 6, the no-cap choice and the WR-06 exposure.
- Restart-loop guard: the paper arguments parse with the runtime's real `build_parser()`; `REFUSAL_CODES == {3, 4, 5, 6}` and excludes 1 and 7; a seeded service without the flag is reported by the same checker.
- `docker compose -p trading-soak --profile paper config` renders with every volume named `trading-soak_*` (separate pgdata from the development stack).
- `deploy/soak.env.example` holds exactly `ALLOWED_ENV_NAMES`, the BACKUP_ names of `.env.example` and `IMAGE_TAG`, all empty, with a header on the shared env_file exposure and the BINANCE start refusal.
- `deploy/compose-soak.sh` refuses `down` with `-v`, `--volumes` or a short cluster containing v, for the project given by `-p`, `--project-name`, `--project-name=` or `COMPOSE_PROJECT_NAME`; any other project name is refused; a scan of runbook code blocks and `deploy/*.sh` (with a negative control) finds no unguarded use.

## Task Commits

1. **Task 1 (tracer): paper service with probe, renders for the soak project**
   - RED `d4f1cc0` (test), GREEN `2ca2197` (feat)
2. **Task 2: soak environment template**
   - RED `42544ed` (test), GREEN `ebe2f4b` (feat)
3. **Task 3: down -v guard wrapper**
   - RED `aeb7426` (test), GREEN `24ad078` (feat)
4. **Deviation (Rule 3): deploy guide card** - `4ebdc2b` (docs)

**Plan metadata:** the SUMMARY commit follows this file.

The tracer gate was re-run end-to-end (static checks plus the compose render) before the expansion tasks; it passed.

## Files Created/Modified

- `docker-compose.yml` - paper service block and comment
- `deploy/compose-soak.sh` - soak wrapper (mode 100755), predicates `soak_args_remove_volumes` and `soak_args_name_other_project`
- `deploy/soak.env.example` - names only
- `tests/test_soak_compose.py` - 30 tests across the three groups
- `tests/test_deploy_compose.py` - paper placeholder case removed, paper probe asserted
- `docs/operations/DEPLOY_GUIDE.vi.md` - card, step 7.5 text, quick-reference row, source lines

## Decisions Made

See key-decisions. The threshold-free planner choices of the plan (restart policy, hold flag, probe timing) were implemented as written. Nothing belonging to the user was decided.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Vietnamese deploy guide requires a card for every deploy script**
- **Found during:** wider verification after Task 3
- **Issue:** `tests/test_deploy_guide_vi.py` (two tests) failed because the new `deploy/compose-soak.sh` and `deploy/soak.env.example` had no card or mention in `docs/operations/DEPLOY_GUIDE.vi.md`.
- **Fix:** added the operation card, a section 14 quick-reference row, updated the step 7.5 text and the source lines. The plan table rows (16-32 still `[CHƯA XÂY]`) and the 14/50 progress figure were left untouched; the guide is maintained as a whole and many rows (for example 16-15 to 16-26) already lag.
- **Files modified:** docs/operations/DEPLOY_GUIDE.vi.md
- **Verification:** `tests/test_deploy_guide_vi.py` passes; the deploy, compose, runbook and docs subset of the suite passes.
- **Committed in:** 4ebdc2b

**2. [Rule 2 - Missing critical] Wrapper also refuses another project name**
- **Found during:** Task 3 design
- **Issue:** the plan only required the `down -v` refusal; a `-p trading` argument would have pointed the soak wrapper at the development stack.
- **Fix:** `soak_args_name_other_project` refuses it; tested.
- **Committed in:** 24ad078

**3. [Rule 3 - Blocking] No YAML library for the static compose test**
- **Found during:** Task 1
- **Issue:** the plan says "static, YAML parse", but the project has no PyYAML and AGENTS.md forbids adding a dependency outside `uv add` with a lock change.
- **Fix:** the static tests slice the service block from the file text and parse its one-line lists as JSON; the compose-render test covers the resolved view.
- **Committed in:** d4f1cc0 and 2ca2197

---

**Total deviations:** 3 auto-fixed (1 Rule 2, 2 Rule 3). **Impact:** no scope creep beyond the guide card.

## TDD Gate Compliance

RED (`test(16-32)`) precedes GREEN (`feat(16-32)`) for all three tasks. For Task 2 the first RED run crashed on a missing file, which is not an assertion; the tests were changed to assert that the file exists and re-run, and the committed RED fails on that assertion. The `gsd_run check tdd-red-evidence` record was not produced (the verb was not available in this session); the failing targets were confirmed by hand from pytest output.

## Issues Encountered

- A first `ruff check` flagged import order and one long line in the test module (imports were used only by later tasks); fixed with `ruff check --fix` and `ruff format` before the Task 3 GREEN commit.
- Not run here: tests marked docker, shellcheck on CI, and anything on the EC2 host. The wrapper was exercised under `DRY_RUN=1` only; no container was started.

## Known Stubs

None. The `live` service in `docker-compose.yml` is still the Phase 24 placeholder by design.

## Threat Flags

None. T-16-74 (no BINANCE_ name in the template, tested), T-16-75 (guard plus scan, tested) and T-16-76 (BACKUP_ exposure accepted, documented in the template, compose comment and guide) are covered.

## User Setup Required

None for this plan. Creating the real soak env file on the host (values from the off-host secrets file, mode 0600) belongs to the host deployment plans.

## Next Phase Readiness

- Ready for 16-33 (soak runbook section and the pinned-image recipe, a user decision) and 16-40.
- The runbook (`docs/operations/RUNBOOK.md`) still describes `paper` as a placeholder in section 13.6; plan 16-33 owns that edit. The Vietnamese guide plan table rows and progress count are for the guide owner to refresh.

## Self-Check: PASSED

- Files found: docker-compose.yml, deploy/compose-soak.sh, deploy/soak.env.example, tests/test_soak_compose.py, tests/test_deploy_compose.py, docs/operations/DEPLOY_GUIDE.vi.md.
- Commits found: d4f1cc0, 2ca2197, 42544ed, ebe2f4b, aeb7426, 24ad078, 4ebdc2b.
- `ruff check`, `ruff format --check` on the test modules and `mypy src` pass; the plan verify command passes with no skips.

---
*Phase: 16-paper-runtime-composition*
*Completed: 2026-10-10*
