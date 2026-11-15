---
phase: 22-leverage-margin-liquidation-guard
plan: 06
subsystem: adapters
status: complete
tags: [binance, adapter, leverage, margin, signed-calls, shadow-isolation]
requirements-addressed: [EXEC-01]
requires: [22-01]
provides:
  - "BinanceUsdmAdapter.change_margin_type(*, symbol, margin_type) -> None (POST /fapi/v1/marginType)"
  - "BinanceUsdmAdapter.change_initial_leverage(*, symbol, leverage) -> None (POST /fapi/v1/leverage)"
affects: [22-11]
tech-stack:
  added: []
  patterns:
    - "mutating configuration POST = one _sdk_call(CallKind.PLACEMENT, ...): never retried, never slept on, original exception re-raised"
key-files:
  created: []
  modified:
    - src/adapters/binance_usdm.py
    - tests/test_leverage_margin_adapter.py
    - tests/test_binance_usdm_signed_calls.py
    - tests/test_paper_shadow_isolation.py
    - tests/test_binance_public.py
key-decisions:
  - "Both calls use CallKind.PLACEMENT (CallKind has no configuration kind, 22-RESEARCH Open Question 5), so the registry's never-retried and gate tests cover them unchanged."
  - "The answer body is never read: the guard (22-11) decides by a symbol_config_snapshot read."
  - "No cap, no drift-guard check in the adapter: the cap and target belong to the guard (D-02)."
commits: 2
plan_head_before: f896ab6138a7193bb7b25079d4eb8888cecc4f0d
plan_head_after: be5bfb50e9e2a697497c5363caa606da1f645e80
actuals:
  tokens: 9000
  tasks: 2
  commits: 2
metrics:
  completed: 2026-10-24
---

# Phase 22 Plan 06: Margin-type and leverage change calls Summary

The adapter can change one symbol's margin type and initial leverage with exactly one signed, gated, never-retried SDK call each (validated before sending, answer body ignored); the signed registry and the shadow isolation control both count twenty, and the SHADOW closure provably cannot reach either call.

## What was built

- `change_margin_type(*, symbol, margin_type) -> None`: validates a non-empty text symbol and a margin type of exactly "ISOLATED" or "CROSSED" (membership, case-sensitive), converts it with `ChangeMarginTypeMarginTypeEnum` (lazy SDK import), then one `_sdk_call(CallKind.PLACEMENT, rest_api.change_margin_type, ...)`. Docstring records the -4046 same-type error and that only a `symbol_config_snapshot` read decides.
- `change_initial_leverage(*, symbol, leverage) -> None`: non-empty text symbol; leverage an int, not a bool (TypeError otherwise), at least 1 (ValueError); one PLACEMENT `_sdk_call`. No upper bound (125 passes through); docstring explains the symbol-specific maximum and -4161.
- Pins: `SIGNED` (20), `SIGNATURE_SNAPSHOTS`, `_payloads` (so `SDK_NAMES` grows), the count test is `test_the_signed_set_is_the_twenty_methods`, comments updated; `ORDER_SURFACE` of the shadow isolation test gains both names (negative control and layer-3 class spies now cover them); `FORBIDDEN_METHODS` of `tests/test_binance_public.py` gains both; adapter module docstring table has two rows and says "all twenty SDK methods".
- 35 new test cases (16 test functions) in `tests/test_leverage_margin_adapter.py` (kwargs and recv window, SDK enum members, bad margin types/symbols/leverages refused with zero SDK calls, answer not read, original exception identity and one call, no policy, ban and pause refusal). The registry tests (418/429 never retried, -1008, -1021 hook once, drift guard consulted only by `place_entry`, signature unchanged) run on both methods.

## Task commits

| Task | Commit | Description |
|---|---|---|
| 1 (tracer) | b288cb25 | `change_margin_type`, registry row 19, ORDER_SURFACE entry |
| 2 | be5bfb50 | `change_initial_leverage`, registry at twenty, public-surface ban, docstring |

Tracer feedback gate: Task 1's `<verify>` is automated only; it was re-run after the commit with the Task 2 set (all green) before the plan was considered done. Red was observed for Task 1 (AttributeError on the missing method) before implementing; Task 2 tests were written together with the pins and run after the implementation.

## Verification

- `uv run pytest -m "not docker" tests/test_leverage_margin_adapter.py tests/test_binance_usdm_signed_calls.py tests/test_paper_shadow_isolation.py tests/test_binance_public.py tests/test_binance_usdm_source_guard.py tests/test_binance_usdm_error_routing.py`: all passed.
- Gate files `tests/test_phase18_gate.py` .. `tests/test_phase21_gate.py`: all passed except `test_phase21_gate.py::test_invariant_6_the_migration_head_is_0011_risk_reservations`, which fails because a wave-2 sibling's untracked migration `src/db/alembic/versions/0012_reservation_margin.py` is now the head. Out of this plan's files; not touched (re-run once, same result).
- `uv run mypy src/adapters/binance_usdm.py`: no issues. `uv run ruff check` and `uv run ruff format --check` on the five touched Python files: clean.
- `git diff --exit-code -- pyproject.toml uv.lock docs/DECISIONS.md params config`: clean. `git log --grep="^[a-z]*(22-06):" -- config params src/execution src/risk src/domain src/persistence` prints nothing.
- Line endings kept: `src/adapters/binance_usdm.py`, `tests/test_binance_usdm_signed_calls.py`, `tests/test_paper_shadow_isolation.py`, `tests/test_binance_public.py` are CRLF in the working tree (edited bytes-aware); `tests/test_leverage_margin_adapter.py` is LF.
- Evidence label: executed unit tests with a fake SDK [DESIGN]; the exchange behaviour of the two calls on the Demo host is unobserved (owner-run case `symbol_config_change_to_isolated`, plan 22-05). No network call was made.

## Deviations from Plan

None in scope. Notes: the Task 1 commit sets the count test to 19 (the registry then holds 19 methods) and Task 2 renames it and raises it to 20, as the task split implies. `commits: 2` counts this plan's own commits; the `plan_head_before..HEAD` range was also 2 at write time (siblings had not committed yet).

## Known Stubs

None.

## Threat Flags

None. Both new calls were in the plan's threat model (T-22-15..T-22-18); no new surface beyond it.

## Self-Check: PASSED

- src/adapters/binance_usdm.py defines `change_margin_type` and `change_initial_leverage` (one line each).
- Commits b288cb25 and be5bfb50 are ancestors of HEAD.
