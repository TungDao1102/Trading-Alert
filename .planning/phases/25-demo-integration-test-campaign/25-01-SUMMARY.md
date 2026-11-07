---
phase: 25-demo-integration-test-campaign
plan: 01
subsystem: testing
tags: [pytest, demo, collection-hook, env-guard, OPS-02]
requires: []
provides:
  - "`demo` pytest marker and skip-by-default collection hook (tests/conftest.py)"
  - "tests/demo/ package with session guard and S00 preflight"
  - "tests/support/demo_guard.py assert_demo_run_environment"
  - "TESTING_STRATEGY 12.2 and an AGENTS.md bullet naming the demo selection as owner-only"
affects: [25-02, 25-03, 25-04, 25-05, 25-06, 25-07, 25-08, 25-09, 25-10]
tech-stack:
  added: []
  patterns:
    - "owner-only selection: plain-skip hook keyed on -m demo plus TRADING_DEMO_RUN=1"
    - "refusal messages name variables, never values (sentinel scan)"
key-files:
  created:
    - tests/demo/__init__.py
    - tests/demo/conftest.py
    - tests/demo/test_demo_s00_preflight.py
    - tests/support/demo_guard.py
    - tests/test_demo_marker_guard.py
    - tests/test_demo_env_guard.py
  modified:
    - pyproject.toml
    - tests/conftest.py
    - docs/testing/TESTING_STRATEGY.md
    - AGENTS.md
key-decisions:
  - "D-03 as corrected by research: the CI command -m \"not docker\" does not exclude a demo marker, so a collection hook adds a plain skip (never infra_skip, which fails under TRADING_CI_STRICT=1)."
requirements-completed: [OPS-02, EXEC-01]
status: complete
duration: 25min
completed: 2026-11-07
commits: 5
plan_head_before: f7ab1e835841fa51ce96c3a3c0d032e10ddfac25
plan_head_after: 81c809b99e5f7bf73f37cd8476fe22290041da5e
actuals:
  tokens: 5200
  tasks: 3
  commits: 5
---

# Phase 25 Plan 01: Demo selection, hook and session guard Summary

The Binance Demo scenario suite is now its own owner-only pytest selection: a registered `demo` marker, a plain-skip collection hook, a session env guard that refuses LIVE names, xdist workers and non-DEMO mode, and docs that tell agents never to run it.

## Tasks

| Task | Name | Commits |
|------|------|---------|
| 1 | Tracer: marker, collection hook, S00 preflight, marker guard | RED 19935c1b, GREEN 6943e07b |
| 2 | Session guard (`assert_demo_run_environment`, `tests/demo/conftest.py`) | RED 7eb2fd97, GREEN c1ac3255 |
| 3 | TESTING_STRATEGY 12.2 and AGENTS.md bullet | 81c809b9 |

## Verification

- `uv run pytest -m "not docker" tests/test_demo_marker_guard.py tests/test_demo_env_guard.py tests/test_agents_md.py tests/demo -x -q -rs`: all passed, tests/demo reports 1 skipped, no passed or failed demo test.
- The strict-mode child run (`TRADING_CI_STRICT=1`, no `TRADING_DEMO_RUN`) exits 0 with the demo item SKIPPED.
- Scoped ruff check and format check clean; `uv run mypy src` clean (291 files); `uv lock --check` exits 0; `verify_decision_alignment.py all` ALL_PASS.
- Acceptance: `demo:` marker present in pyproject; `git grep infra_skip -- tests/conftest.py` prints only the docker line; `TRADING_DEMO_RUN` appears in AGENTS.md and TESTING_STRATEGY.md.

## Deviations from Plan

None in behavior. Small notes:
- The S00 test imports `Environment` from `src.adapters.binance_client` (the plan interface did not name the module; it is not in `src.domain.enums`).
- A first docstring in the hook mentioned `infra_skip`, which would have made the plan's `git grep` acceptance print 2 lines; reworded to "the docker helper".
- `tests/demo/conftest.py` was committed with the Task 2 GREEN commit (not the RED commit) so the RED commit holds tests only.
- Edits to CRLF working-tree files (pyproject.toml, tests/conftest.py, AGENTS.md, TESTING_STRATEGY.md) were done bytes-aware with CRLF kept.

## Known limits

- The `tests/demo/conftest.py` fixture itself (the `pytest.fail` translation) is not exercised by any agent-run test, because that would need `pytest -m demo` with `TRADING_DEMO_RUN=1`, which agents must not run. The logic it calls (`assert_demo_run_environment`) is unit-tested in `tests/test_demo_env_guard.py`; the fixture is a 4-line wrapper first exercised in the owner's run.
- The hook skip applies to every item carrying the mark; a test under `tests/demo` without the mark would not be skipped, which is what the marker guard prevents.

## Known Stubs

None.

## Threat Flags

None. No new network endpoint, auth path or schema; the only dependency-related file touched is the markers list in pyproject.toml (`uv lock --check` exit 0).

## Self-Check: PASSED

All created files exist and all five commits are ancestors of HEAD (`git log f7ab1e83..HEAD` lists them).
