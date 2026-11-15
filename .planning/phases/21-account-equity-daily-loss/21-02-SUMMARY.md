---
phase: 21-account-equity-daily-loss
plan: 02
subsystem: execution
tags: [execution-limits, equity-age, fail-closed, NOT_CONFIGURED, F-012]
requires:
  - phase: 20
    provides: "execution-limits-v1.toml loader, ALERT_ONLY_LIMIT_KEYS, the <section>_<key> field rule (plan 20-01, 20-28)"
provides:
  - "[account] section and [provenance.account] in config/execution/execution-limits-v1.toml, max_equity_age_ms = NOT_CONFIGURED"
  - "EXECUTION_LIMIT_KEYS['account'], EXECUTION_LIMIT_FIELDS['account.max_equity_age_ms'], ExecutionLimits.account_max_equity_age_ms (required, not alert-only)"
  - "TEST_ONLY value 9137 for account.max_equity_age_ms in tests/support/execution_limits.py"
affects: [21-07, 21-13]
tech-stack:
  added: []
  patterns: ["required execution limit: loaded, validated, provenance-labelled, named by require_live_ready while NOT_CONFIGURED"]
key-files:
  created: []
  modified:
    - config/execution/execution-limits-v1.toml
    - config/execution/README.md
    - src/execution/execution_limits.py
    - tests/support/execution_limits.py
    - tests/test_execution_limits.py
    - tests/test_no_unratified_defaults.py
    - tests/test_phase18_gate.py
key-decisions:
  - "account.max_equity_age_ms is a REQUIRED key (not in ALERT_ONLY_LIMIT_KEYS): while it is NOT_CONFIGURED the live path refuses, naming the key; no number is chosen (D-03, owner-open O-1)."
  - "The field is account_max_equity_age_ms (the <section>_<key> rule); both spellings are in GUARDED_NAMES, 52 -> 54."
status: complete
requirements-addressed: [RISK-01, RISK-02]
duration: ~25 min
completed: 2026-10-23
commits: 2
plan_head_before: 4066b4bb6632edfeed320a9b8df93904996e8777
plan_head_after: 16693e0b
actuals:
  tokens: 28000
  tasks: 2
  commits: 2
---

# Phase 21 Plan 02: account.max_equity_age_ms execution limit Summary

**The sixteenth execution limit, `account.max_equity_age_ms`, is added as a REQUIRED key that stays `NOT_CONFIGURED` (value and provenance), loads into `ExecutionLimits.account_max_equity_age_ms`, is named by `require_live_ready()`, and is guarded against a numeric default under both spellings. No number exists for it outside TEST_ONLY test support.**

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 (tracer) | 017feeeb | TOML `[account]` + `[provenance.account]`, loader/field/dataclass entry, TEST_ONLY 9137, tests, README key line |
| 2 | 16693e0b | README counts (sixteen keys, fifteen required, one alert-only), GUARDED_NAMES pins 52 -> 54 in `test_no_unratified_defaults.py` and `test_phase18_gate.py`, both-spelling assertion |

`commits: 2` counts the commits whose subject starts with `(21-02)`. The tree is shared with sibling plans 21-03..21-06, so `git rev-list plan_head_before..plan_head_after` also contains their commits; the SUMMARY commit follows.

## What was built

- `config/execution/execution-limits-v1.toml`: header comment line, `[account] max_equity_age_ms = "NOT_CONFIGURED"` after `[alerts]`, `[provenance.account]` after `[provenance.alerts]`. (The file has LF endings in the working tree, not CRLF as the plan said; kept as is.)
- `src/execution/execution_limits.py`: `"account": ("max_equity_age_ms",)` as the last section, the field mapping, the dataclass field (no default), docstring text (meaning, unit, stale predicate, required, O-1) and updated counts. `ALERT_ONLY_LIMIT_KEYS` untouched.
- Tests: the committed file loads with the key unset and `unset_keys()` ends with it (15 required keys); `require_live_ready()` names it with no digit in the message; `unset_alert_only_keys()` is still only `reconcile.entry_stale_grace_ms`; a set value (5, DECISION) loads; missing section / key / label, bool, float, zero, negative, wrong strings, PLACEHOLDER, NOT_CONFIGURED-with-int and DECISION-with-unset all refuse naming the key and not the value; `test_only_execution_limits()` sets 9137 and `account_max_equity_age_ms=None` leaves it unset.
- README: `### [account]` subsection (one key per line, parsed by the README test), meaning, unit, stale predicate, required, consumers 21-07 and 21-13, O-1 open; counts reworded.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] README key line moved into Task 1.**
- **Found during:** Task 1
- **Issue:** `test_the_readme_lists_exactly_the_execution_limit_keys` (in `tests/test_execution_limits.py`, Task 1's verify) fails as soon as `EXECUTION_LIMIT_KEYS` has the new key unless the README lists it, so the Task 1 commit could not be green without it.
- **Fix:** the `### [account]` subsection went into the Task 1 commit; the count wording followed in Task 2.
- **Files modified:** config/execution/README.md
- **Commit:** 017feeeb

**2. [Plan reference wrong] docs/operations/SECURITY_AND_OPERATIONS.md not edited.**
- The plan (and its `files_modified`) name "lines ~91-93" of that file for the sentence about the fifteenth, alert-only key and the fourteen required keys. That sentence is in `config/execution/README.md` lines 91-93 (now reworded there); `docs/operations/SECURITY_AND_OPERATIONS.md` contains no such sentence (it only mentions `alerts.dedupe_window_ms` in the Phase 20 alert paragraph, which stays true). Nothing was changed in that file.

**3. Other pinned unset tuples.** `grep -rn "alerts.dedupe_window_ms" tests/` found only `tests/test_execution_limits.py` (updated), `tests/test_phase20_gate.py` (a subset check of the seven Phase 20 keys, still true, not edited), plus unrelated uses in `test_alerts.py` and `test_reconcile_loop.py`. Nothing else needed a pin.

## Verification (executed unit tests [DESIGN]; no [DEMO] claim; LIVE stays blocked)

- `uv run pytest -m "not docker" tests/test_execution_limits.py tests/test_no_unratified_defaults.py tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py` -> all passed (run sequentially, no xdist; 0 failures).
- `uv run pytest -m "not docker" tests/test_execution_manager.py tests/test_reconcile_stale_entry.py tests/test_demo_rehearsal_flow.py tests/test_alerts.py` -> 261 passed (extra: files that load or build `ExecutionLimits`).
- `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_persistence_exit_evidence_pg.py -x` -> 31 passed.
- `uv run mypy src/execution/execution_limits.py` -> no issues; scoped `ruff check` and `ruff format --check` on the five python files -> clean; `uv run python scripts/verify_decision_alignment.py all` -> ALL_PASS.
- `git diff --exit-code -- config/binance params src/paper pyproject.toml uv.lock` -> exit 0.
- No full-suite run, no network, no Demo script.

## Known Stubs

None. TEST_ONLY value 9137 lives only in `tests/support/execution_limits.py` and is not imported by production code (guarded by `test_no_production_file_imports_the_test_only_limits`).

## Threat Flags

None. T-21-02 and T-21-03 are mitigated as planned (refusal matrix; both spellings guarded); T-21-SC: no dependency change.

## For the owner

- O-1 stays open: `account.max_equity_age_ms` is `NOT_CONFIGURED` with provenance `NOT_CONFIGURED`. Setting it needs a DECISIONS row and the label `DECISION`. Until then the live path refuses, naming `account.max_equity_age_ms`, and so does every test that builds limits from the committed file.
- No requirement was marked complete (RISK-01, RISK-02 are only listed under `requirements-addressed`).

## Self-Check: PASSED

- config/execution/execution-limits-v1.toml, src/execution/execution_limits.py, tests/support/execution_limits.py, tests/test_execution_limits.py, config/execution/README.md, tests/test_no_unratified_defaults.py, tests/test_phase18_gate.py exist and are committed.
- Commits 017feeeb and 16693e0b exist on `develop`.
