---
phase: 16-paper-runtime-composition
plan: 53
subsystem: deploy / rehearsal isolation (gap closure of the 16-40 "Gap noticed" and "Open question")
tags: [rehearsal, compose-wrapper, binance-refusal, t-16-92, rev-03]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plan 16-33 (RUNBOOK 20, deploy/compose-soak.sh style), 16-39 (scripts/shadow_rehearsal.py), 16-40 (Task 3 rehearsal instructions)"
provides:
  - "deploy/compose-rehearsal.sh: guarded docker compose wrapper for the trading-rehearsal project (env file from TRADING_ENV_FILE outside the checkout, BINANCE_ names refused in environment and file, other project names and --env-file refused, running trading-soak refused, --dry-run prints only)"
  - "scripts/shadow_rehearsal.py refuses BINANCE_* in --dry-run too (exit 3, names only), check moved ahead of the mode branch"
  - "RUNBOOK 20.4, DEPLOY_GUIDE.vi.md (card, quick-reference row, source lines) and the 16-40-SUMMARY Task 3 steps carry the exact commands"
affects: [16-40 Task 3 (operator steps now use the wrapper)]

requirements-completed: []

status: complete
actuals:
  tokens: 14000
  tasks: 2
  commits: 3
plan_head_before: 78b8b1af82bcbcb5bb563030aee7dcc6d8e8b4b6
plan_head_after: 8e7701ef67b137ee7d91113d05c5dcb8703264a8
commits: 3

tech-stack:
  added: []
  patterns:
    - "Wrapper tests use a stub docker on PATH that records its arguments and answers the soak probe from an environment variable; no daemon, no network"

key-files:
  created:
    - deploy/compose-rehearsal.sh
    - tests/test_rehearsal_compose.py
    - .planning/phases/16-paper-runtime-composition/16-53-PLAN.md
  modified:
    - scripts/shadow_rehearsal.py
    - tests/test_paper_shadow_isolation.py
    - tests/test_paper_test_signal_rehearsal.py
    - docs/operations/RUNBOOK.md
    - docs/operations/DEPLOY_GUIDE.vi.md
    - .planning/phases/16-paper-runtime-composition/16-40-SUMMARY.md

key-decisions:
  - "The project name alone gives the rehearsal its own database volume (trading-rehearsal_pgdata); no compose file change"
  - "The soak check is any running container of the project (not only the paper runtime): the soak PostgreSQL shares the default host port and the bot token must have one getUpdates consumer. A failing probe fails closed. The dry run does not call docker, so it only announces the check"
  - "--dry-run is accepted only as the first argument so it cannot collide with compose flags; DRY_RUN=1 behaves the same (lib.sh convention)"
  - "A required env file (unset, missing or inside the checkout is refused, also in dry-run) instead of falling back to .env, which is the soak or development file"

patterns-established:
  - "Names-only refusals: the BINANCE_ scan of the env file prints the variable name and never the line"

coverage:
  - deliverable: "wrapper pins the project, prints the command on --dry-run without calling docker"
    verification:
      - {kind: pytest, ref: "tests/test_rehearsal_compose.py::test_dry_run_prints_the_project_command_and_calls_no_docker", status: pass}
      - {kind: pytest, ref: "tests/test_rehearsal_compose.py::test_a_real_run_probes_the_soak_then_forwards_exactly_the_command", status: pass}
  - deliverable: "refusals before any compose call (env file, BINANCE_ names, other project, --env-file, running soak)"
    verification:
      - {kind: pytest, ref: "tests/test_rehearsal_compose.py (refusal tests)", status: pass}
  - deliverable: "shadow_rehearsal --dry-run refuses BINANCE_*"
    verification:
      - {kind: pytest, ref: "tests/test_paper_test_signal_rehearsal.py::test_any_binance_variable_refuses_the_dry_run_too_and_only_the_name_is_printed", status: pass}
  - deliverable: "docs trace tests accept the new script, card and commands"
    verification:
      - {kind: pytest, ref: "tests/test_deploy_guide_vi.py, tests/test_deploy_docs.py, tests/test_soak_runbook.py, tests/test_soak_compose.py", status: pass}
      - {kind: shellcheck, ref: "tests/test_deploy_scripts.py::test_script_passes_shellcheck[compose-rehearsal.sh]", status: not-run}
---

# Phase 16 Plan 53: rehearsal compose wrapper and dry-run BINANCE_ refusal Summary

`deploy/compose-rehearsal.sh` runs docker compose only as `trading-rehearsal` with an outside-the-checkout env file and refuses BINANCE_ names, other projects and a running soak; `scripts/shadow_rehearsal.py --dry-run` now refuses BINANCE_* like the live mode.

## What was built

- **Wrapper** (`deploy/compose-rehearsal.sh`, mode 100755): mirrors `compose-soak.sh` (lib.sh `compose_init`, `run`, `die`; project flag placed right after `docker compose`). Refusals, all exit 1 before any compose call: `TRADING_ENV_FILE` unset, unreadable or inside the checkout; a `BINANCE_` name in the process environment or in the env file (export and indented forms, comments ignored; names only); `-p` / `--project-name` for another project; `--env-file`; any running container labelled `com.docker.compose.project=trading-soak`; a failing `docker ps` probe. No compose arguments is exit 2. `--dry-run` (first argument) or `DRY_RUN=1` prints `+ docker compose -p trading-rehearsal --env-file <file> ...` and calls no docker. `COMPOSE_PROJECT_NAME` is overridden, not honoured.
- **Source change**: in `main()` of `scripts/shadow_rehearsal.py` the `refuse_trade_capable_env` block now runs before `if args.dry_run:`; module docstring and exit-code table updated. Live-mode order of refusals is unchanged (BINANCE_ first, then the operator flag).
- **Docs**: RUNBOOK 20.4 (paragraph and four commands), Vietnamese guide (intro paragraph, nine-field card for the script, section 14 row, two source lines), 16-40-SUMMARY Task 3 step 2 plus the Gap and Open-question notes marked closed.

## Verification

Targeted pytest run (tests/test_rehearsal_compose.py, test_paper_shadow_isolation.py, test_paper_test_signal_rehearsal.py, test_soak_compose.py, test_deploy_docs.py, test_deploy_guide_vi.py, test_soak_runbook.py, test_env_example.py, test_paper_runtime_env.py, test_deploy_scripts.py): all pass, skips only for tools missing on this machine. `uv run mypy src`, `uv run ruff check`, `uv run ruff format --check`: clean.

## Deviations from Plan

**1. [Rule 3 - Blocking] Guide card and quick-reference row instead of a "short paragraph"**
- **Found during:** Task 2
- **Issue:** tests/test_deploy_guide_vi.py requires, for every `deploy/*.sh`, a nine-field operation card (with a `Chạy thử` field when the script has `--dry-run`), a section 14 row naming the script and its flags, and every deploy file named in the guide.
- **Fix:** card + short intro paragraph + row + source lines in `docs/operations/DEPLOY_GUIDE.vi.md`.
- **Commit:** 8e7701e

**2. [Test pin] `tests/test_paper_shadow_isolation.py`** pinned the old behaviour only in a docstring ("The dry run does not run the BINANCE_ refusal"); that test passes an empty environment and stays valid. Only the docstring changed. `tests/test_paper_test_signal_rehearsal.py` pinned nothing; one test was added there.

No hash-pinned digest or fixture moved; `evidence/16-40-rehearsal-dryrun.json` was not regenerated.

## Not run

- shellcheck on `deploy/compose-rehearsal.sh` (`tests/test_deploy_scripts.py::test_script_passes_shellcheck`): shellcheck is not installed here, the test skips. `bash -n` passes.
- The wrapper against a real Docker daemon, a real env file or a real running soak: never run (no docker; stub only).
- PostgreSQL variants and the full test suite (memory).

## Threat Flags

None. The wrapper adds no network surface; it reads an env file for variable NAMES only and never prints a value.

## Self-Check: PASSED

deploy/compose-rehearsal.sh, tests/test_rehearsal_compose.py, 16-53-PLAN.md present; commits bfe5b21, b4c5717, 8e7701e present.
