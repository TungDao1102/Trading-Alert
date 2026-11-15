---
phase: 25-demo-integration-test-campaign
plan: 05
subsystem: live-ast-guards
tags: [D-08, criterion-2, ast-guard, same-code-path, EXEC-01, EXEC-02]
requires: []
provides:
  - "tests/test_demo_same_code_path.py: AST guard that Demo and live share one code path (D-08): zero Environment.DEMO in src/execution and src/risk, a pinned reasoned allow-list in src/live, no mode parameter on the placement chain, no test edge in production assembly"
affects: [25-06]
tech-stack:
  added: []
  patterns:
    - "exact-path allow-list with a non-empty reason per entry, compared as a set with the AST scan (as WALL_CLOCK_EDGE_ALLOW_LIST)"
    - "a lookup helper raises LookupError when its target function or call is missing, so a rename cannot make a check vacuous"
key-files:
  created:
    - tests/test_demo_same_code_path.py
  modified: []
key-decisions:
  - "The allow-list is compared by exact repo-relative path; the same text under a renamed file is not excused (negative control)."
  - "A `**` expansion in the default_assemble build_wiring call counts as a violation, because it could carry exchange_edge."
requirements-completed: [EXEC-01, EXEC-02]
status: complete
actuals:
  tokens: 5500
  tasks: 2
  commits: 2
plan_head_before: 12ae13e863c2635d7f81c2ffe47190595bc5f80a
plan_head_after: 3379fa0a5d522a74a94a799bd671fa7c4f344dde
---

# Phase 25 Plan 05: Demo same-code-path AST guard Summary

Criterion 2 ("same code path as live, only endpoint and keys differ", D-08) is now machine-checked by one test module that passes on today's tree and fails when a Demo-only branch appears in `src/execution`, `src/risk` or an unlisted `src/live` module. No file under `src` was edited; no dependency changed.

## Commits

| Task | Commit | Files |
|------|--------|-------|
| 1 (tracer) | ae5bf3e7 | tests/test_demo_same_code_path.py |
| 2 | 3379fa0a | tests/test_demo_same_code_path.py |

## What is pinned

- `src/execution` and `src/risk`: zero `Environment.DEMO`; as hardening, zero `.DEMO` attribute of any name (so `HealthRuntimeMode.DEMO` or an alias cannot slip in).
- `src/live`: the set of files referencing `Environment.DEMO` equals the keys of `DEMO_BRANCH_ALLOW_LIST` (six files, confirmed by the AST scan of HEAD; each key exists on disk).
- `execute_approved_plan` (`src/execution/manager.py`) and `BinanceUsdmAdapter.place_entry` (`src/adapters/binance_usdm.py`) have no argument named `mode`, `environment` or `env` (positional, keyword-only, `*args`, `**kwargs` all counted).
- `default_assemble`'s `build_wiring(...)` call passes no `exchange_edge` keyword and no `**` expansion.
- No file of `src/execution` or `src/risk` imports `tests` or `scripts` (parametrized per file).

## The allow-list (DEMO_BRANCH_ALLOW_LIST)

| File | Reason |
|------|--------|
| src/live/config.py | mode parsing: `ACCEPTED_MODES` maps the text DEMO to `Environment.DEMO`; the opposite-credential rule picks the other mode's variables to refuse |
| src/live/enablement.py | `enable_demo` refuses any mode that is not DEMO: the in-process enable exists only in DEMO, LIVE keeps the human step |
| src/live/smoke_injection.py | the `/demo_signal` injector and `DemoSmokeSignalSource` exist only in DEMO; LIVE and TESTNET never get the command |
| src/live/startup.py | DEMO start rule: the HEALTH and ENABLE steps run in DEMO only, LIVE skips them with the human-enable code |
| src/live/wiring.py | `demo_degraded_allowed` for the health producer (D056 (2)) and the LINK_DEMO_SIGNAL check that the injector exists in DEMO and nowhere else |
| src/live/wiring_parts.py | the DEMO-only kill-gate sources rule (D092): explicit DEMO rule, the persisted evaluated state in every other mode |

## Negative controls (tmp_path or inline source)

Seeded `src/execution/x.py` with `Environment.DEMO` is reported; a seeded `src/live/new_mod.py` outside the list breaks the set comparison; a renamed copy of an allow-listed file is not excused; docstring, comment and string text are not references; a `HealthRuntimeMode.DEMO` is found only by the any-owner scan; a `mode`/`environment`/`env` argument (three spellings of position) is found; a seeded `exchange_edge=` keyword and a `**extra` expansion are found; a seeded `tests`/`scripts` import is found; a missing function or missing `build_wiring` call raises instead of passing empty.

## Verification

- `uv run pytest -m "not docker" tests/test_demo_same_code_path.py tests/test_live_ast_guards.py -x -q`: all passed (138 tests, 0 failed).
- `uv run ruff check` and `uv run ruff format --check` on the new file: clean.
- `uv run mypy src`: no issues in 291 source files. `uv lock --check`: resolved, no change.
- `git diff --exit-code -- src pyproject.toml uv.lock`: exit 0.
- No `pytest -m demo`, no `--execute`, no network call, no `.env` read.

## Deviations from Plan

- **[Rule 2 - hardening, additive]** One extra test: no `.DEMO` attribute of any owner name in `src/execution` and `src/risk`. It passes today (grep and AST scan both show none) and closes the alias hole; no plan truth changed.
- Task 1 is a test-only tracer: the allow-list was derived from the scan of HEAD, so the guard is green on its first run; the negative controls are the red evidence that each rule can fail.

## Known limit

The scanner matches the literal name `Environment`; `import Environment as Env` is not followed (every src module today imports it unaliased from `src.adapters.binance_client`). A Demo branch written as a string compare (`mode == "DEMO"`) is also outside this rule.

## Known Stubs

None.

## Threat Flags

None. T-25-11 and T-25-12 are mitigated by the tests above; T-25-SC: no package added.

## Self-Check: PASSED

- tests/test_demo_same_code_path.py exists; commits ae5bf3e7 and 3379fa0a are ancestors of HEAD.
