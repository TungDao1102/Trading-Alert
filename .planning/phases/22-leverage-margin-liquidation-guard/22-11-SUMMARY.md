---
phase: 22-leverage-margin-liquidation-guard
plan: 11
subsystem: execution
status: complete
tags: [binance, leverage, margin, isolated, config-guard, fail-closed]
requirements-addressed: [EXEC-01, EXEC-02, RISK-02]
requires: [22-01, 22-06]
provides:
  - "SymbolConfigGuard.ensure(*, symbol, symbol_is_flat) -> ConfigGuardResult"
  - "TARGET_LEVERAGE = 5 (D035), TARGET_MARGIN_TYPE = 'ISOLATED', SymbolConfigPort"
  - "plain codes MARGIN_CONFIG_UNVERIFIED, MARGIN_CONFIG_CHANGE_REFUSED, AUTO_ADD_MARGIN_ENABLED"
affects: [22-14, 22-15, 22-16]
tech-stack:
  added: []
  patterns:
    - "single-attempt mutating calls; only the last read decides; exception class name only"
key-files:
  created:
    - src/execution/symbol_config_guard.py
    - tests/support/config_guard_fakes.py
    - tests/test_symbol_config_guard.py
  modified: []
key-decisions:
  - "A failed margin-type POST ends the mutations of the run; the leverage POST is not sent into an unexpected state."
  - "A first read with a field of the wrong type (or isAutoAddMargin not a bool) sends nothing and is MARGIN_CONFIG_UNVERIFIED."
  - "ConfigGuardResult gains a defaulted last field error_types (exception class names) beyond the planned field list, as evidence for the manager's journal."
  - "changed means the verified (margin type, leverage) differs from the first read, so a -4046 that raced a manual change to the target reports changed True with ok True."
commits: 2
plan_head_before: 5d4be18c3d203bc67fc9065a42284f511dec980d
plan_head_after: 37ce83eeb175801b649e00801429df17aa34c679
actuals:
  tokens: 21000
  tasks: 2
  commits: 2
metrics:
  completed: 2026-10-24
---

# Phase 22 Plan 11: Symbol configuration guard Summary

`SymbolConfigGuard.ensure` turns the recorded CROSSED x20 symbol into a verified ISOLATED x5 with at most one marginType POST and one leverage POST, decides only by the closing read, and refuses (or reports unverified) everything else.

## What was built

- `src/execution/symbol_config_guard.py`: constants `TARGET_LEVERAGE` (D035) and `TARGET_MARGIN_TYPE`, the Protocol `SymbolConfigPort`, frozen `ConfigGuardResult`, `SymbolConfigGuard(adapter=, target_leverage=)` (keyword-only, no default; bool, float and text are TypeError, below 1 is ValueError). `ensure`: first read; `isAutoAddMargin` true gives AUTO_ADD_MARGIN_ENABLED before any POST; an exact match (str "ISOLATED", int leverage equal to the target, autoAdd False) sends nothing, flat or not; a mismatch on a non-flat symbol gives MARGIN_CONFIG_CHANGE_REFUSED with zero POSTs; on a flat symbol only the wrong kind is POSTed (margin type first, then leverage), each swallowed with its class name only, a failed margin POST skips the leverage POST; one verification read decides. The result carries the verified margin type, leverage, `max_notional_value`, `changed`, previous configuration and `posts_sent`.
- `tests/support/config_guard_fakes.py`: `StatefulConfigSdk` (state from the recorded fixture, scripted errors, 200-without-change mode, scripted read sequence, ordered call record; any other SDK name is an AttributeError) with `build_config_adapter` (real adapter, TEST_ONLY policy and gate), and `ScriptedConfigAdapter` (scripted reads and POST outcomes).
- `tests/test_symbol_config_guard.py`: 69 cases: tracer call order `[read, marginType, leverage, read]` and `posts_sent == 2`; match costs one read (flat and not flat); idempotence; non-flat refusals; partial mismatches; a 7-exception matrix (-4046, -4047, -4048, -4028, timeout, gate pause, ValueError) for both POSTs in the "still wrong" and the "read shows it" variants; the real adapter with an injected -4047; 200-without-change; unreadable first/verification reads; casing, leverage 4, bool, float, still-CROSSED answers; autoAdd on first and verification read; never two POSTs of a kind and no sleep; no message text in result or logs; CancelledError propagates; constructor and argument validation; AST purity (no wall clock, no adapter/persistence/SDK/sqlalchemy import, no "USDT" literal).

## Task commits

| Task | Commit | Description |
|---|---|---|
| 1 (tracer) | 569cb788 | recorded CROSSED x20 to verified ISOLATED x5 through the real adapter, fakes, tracer tests |
| 2 | 37ce83ee | every failure branch and the full test matrix |

Tracer feedback gate: Task 1's `<verify>` is automated only; it was re-run with the Task 2 set (all green) before the plan was considered done. Red was observed for Task 1 (module not found) before implementing.

## Verification

- `uv run pytest -m "not docker" tests/test_symbol_config_guard.py tests/test_leverage_margin_adapter.py tests/test_paper_shadow_isolation.py -x`: all passed.
- Gate files `tests/test_phase18_gate.py` .. `tests/test_phase21_gate.py`: all passed.
- `uv run mypy src/execution/symbol_config_guard.py`: no issues. `ruff check` and `ruff format --check` on the three files: clean.
- `git diff --exit-code -- pyproject.toml uv.lock docs/DECISIONS.md params config`: clean. `git log --grep="^[a-z]*(22-11):" -- config params src/adapters src/risk src/persistence src/domain` prints nothing.
- Line endings: all three new files LF in the index and working tree (git warns about a future CRLF conversion only; nothing was changed).
- Evidence label: executed unit tests with a stateful fake SDK and the recorded CROSSED x20 symbolConfig (demo-observed, not mainnet) [DESIGN]. The owner Demo run of 2026-10-24 (22-DEMO-RESULTS R-1, R-2) recorded the upper-case ISOLATED casing (so the exact comparison matches the real answer), -4047 with open orders and an unchanged configuration; the fake's `maxNotionalValue` 100000000 after the x5 change is that observation. No network call was made.

## Deviations from Plan

None in scope. Notes: (1) `commits: 2` counts this plan's own commits; `git rev-list --count plan_head_before..HEAD` was 8 at write time because wave-3 siblings (22-10, 22-12, 22-13) committed meanwhile. (2) `error_types` was added to `ConfigGuardResult` (defaulted, last). (3) The first executor run was interrupted by a rate limit after the tracer commit; Task 2 was completed from the uncommitted module state, and the test file was re-written in full.

## Known Stubs

None.

## Threat Flags

None. Threats T-22-35..T-22-39 are mitigated as planned: only the verification read decides; a non-flat mismatch is a zero-POST refusal; at most one POST per kind, asserted over the matrix; autoAdd refused before any POST and at the verification read; only class names kept (capture_logs test with a digit-bearing message). No dependency change.

## Self-Check: PASSED

- src/execution/symbol_config_guard.py, tests/support/config_guard_fakes.py and tests/test_symbol_config_guard.py exist.
- Commits 569cb788 and 37ce83ee are ancestors of HEAD.
