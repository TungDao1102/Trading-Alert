---
phase: 22-leverage-margin-liquidation-guard
plan: 14
subsystem: execution
status: complete
tags: [margin-guard, isolated, liquidation, available-margin, fail-closed, first-refusal-wins, criterion-1, criterion-2, criterion-3, criterion-4]
requirements-addressed: [RISK-01, RISK-02, EXEC-01]
requires: [22-02, 22-04, 22-07, 22-10, 22-11, 22-12]
provides:
  - "src/execution/margin_guard.py: MarginGuardRequest, MarginGuardVerdict, MarginGuardPort, MarginAccountPort, ClaimsPort, ConfigGuardPort, BracketPort, MarginGuard, MARGIN_MODE_UNSUPPORTED"
  - "tests/support/margin_guard_fakes.py: CompositeRest, build_rig/GuardRig (the real-adapter rig plan 22-15 reuses), scripted ports, request()"
affects: [22-15, 22-16]
tech-stack:
  added: []
  patterns:
    - "one fixed-order composition, first refusal wins; every port wrapped in try/except Exception -> UNCERTAIN_ACCOUNT_STATE, class names never reach the verdict"
    - "freshness: refresh, clock read, judge; clock read again after the last await, judge again, then decide"
key-files:
  created:
    - src/execution/margin_guard.py
    - tests/support/margin_guard_fakes.py
    - tests/test_margin_guard.py
  modified: []
key-decisions:
  - "Order is account mode, configuration, liquidation, margin; the leverage after step 1 is cfg.leverage (the one the exchange verified). The liquidation call receives entry_fee_rate=request.fee_rate_entry (plan_check_addenda); no constant, no 0."
  - "The guard re-checks the bracket reading against the owner's bracket bound with its own clock read (the cache already does); a stale, empty, foreign or malformed reading is LIQUIDATION_INPUT_UNAVAILABLE, a port exception is UNCERTAIN_ACCOUNT_STATE."
  - "A configuration result that says ok but whose margin type is not ISOLATED, whose leverage is not a plain int >= 1 or whose maxNotionalValue is not a positive Decimal is UNCERTAIN_ACCOUNT_STATE (defence in depth on the port)."
  - "Configuration evidence: config_changed is posts_sent > 0; the previous configuration rides on a pass always and on a refusal only when a POST was sent."
  - "ClaimsPort.list_margin_claims is a plain call; an awaitable result is also accepted (the store behind it may be async, plan 22-15/Phase 24)."
  - "AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED stays False (owner DECISIONS row needed); the guard passes the module-level name so a test can prove it is the switch."
commits: 2
plan_head_before: bf866093a0f8834a3df05a4d36aa65e59814af47
plan_head_after: af78968a2c030801032000fc0f6ba9d01fb14f2e
actuals:
  tokens: 19900
  tasks: 2
  commits: 2
metrics:
  completed: 2026-10-24
---

# Phase 22 Plan 14: Pre-entry margin guard Summary

**`MarginGuard.evaluate` runs account mode, symbol configuration, liquidation and available margin in one fixed order with the first refusal winning and a plain code each; the recorded Demo CROSSED x20 account flows through the real adapter, equity source, configuration guard and bracket cache to a pass carrying ISOLATED, 5 and the equity 4999.09343961 (demo-observed, not mainnet).**

## What was built

- `src/execution/margin_guard.py`
  - `MarginGuardRequest` (frozen, validated): plan id, symbol, side (LONG/SHORT or `Direction`), quantity, limit price, stop price and mark price (positive finite Decimals), the two fee rates (non-negative Decimals, 0 allowed) and `symbol_is_flat` (bool).
  - `MarginGuardVerdict` (frozen, validated): a pass is `OK` with margin type, leverage and equity; a refusal has a non-OK code and none of the three; `alert_reason`, `config_changed` and the previous configuration are evidence.
  - Ports `MarginGuardPort`, `MarginAccountPort`, `ClaimsPort`, `ConfigGuardPort`, `BracketPort`; `MARGIN_MODE_UNSUPPORTED`.
  - `MarginGuard(config_guard=, brackets=, account=, claims=, clock=, limits=)`. Construction raises `ExecutionLimitsNotConfigured` naming the unset keys among `margin.liquidation_buffer_bps`, `margin.max_bracket_age_ms`, `margin.headroom_bps` (all three named when all are unset); `ValueError` for a non-positive value, `TypeError` for a bad clock, port or limits.
  - `evaluate`: (0) `refresh()`, clock read, `check_margin`; hedge -> `HEDGE_MODE_UNSUPPORTED` (imported), multi-asset -> `MARGIN_MODE_UNSUPPORTED`, unusable -> `UNCERTAIN_ACCOUNT_STATE`, all before any configuration call. (1) `ensure(...)`; its refusal code and alert reason pass through. (2) brackets, bound re-check, notional against `maxNotionalValue` (`NOTIONAL_ABOVE_MAX`, equal passes), `liquidation_verdict(... leverage=cfg.leverage, buffer_bps=limit, entry_fee_rate=request.fee_rate_entry)`. (3) claims, clock read after the last await, `check_margin` again, `other_claims_margin(... resting_orders_netted=AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED)`, `margin_verdict(... leverage=cfg.leverage ...)`.
- `tests/support/margin_guard_fakes.py`: `CompositeRest` serves one real `BinanceUsdmAdapter` by delegating to `_FakeRest` (account), `StatefulConfigSdk` (symbolConfig) and `FakeBracketRest` (brackets) without repeating a payload table; it records one ordered call list, can advance or rewind a `MovingClock` per call and can make a named SDK call fail. `build_rig` returns `GuardRig` (guard, rest, clock, claims, real `LiveEquitySource`, `BracketCache`, `SymbolConfigGuard`). `account_payloads` edits the recorded account JSON per test. Scripted account, configuration, bracket and claims ports share an event list.
- `tests/test_margin_guard.py`: 89 tests. The tracer asserts the exact SDK call order (the three account reads, symbolConfig read, margin POST, leverage POST, verification read, bracket read), `equity_used == Decimal("4999.09343961")`, a second call that sends no POST and reads no brackets, the second clock read, and a reading that ages across the reads (2 s per SDK call, 16 s total against the 9137 ms TEST_ONLY bound) refused as `UNCERTAIN_ACCOUNT_STATE` with the mutation carried as evidence. The matrix has 23 composite scenarios (code, alert reason, calls that must stay at zero, claims calls), the order test over four layers with event spies, the fee tests (stop 65366 passes with fee 0 and is `LIQUIDATION_TOO_CLOSE` with 0.0004; a spy proves `entry_fee_rate == request.fee_rate_entry` for 0, 0.0004 and 0.0007), headroom equality (164.382912 passes, 164.382911 fails), the netting switch, per-port exception tests without message text, malformed answers, construction, value-object validation, no log events, AST purity and `len(RejectionReason) == 21`.

## Task commits

| Task | Commit | Description |
|---|---|---|
| 1 (tracer) | e2b63617 | module, composite fake SDK and rig, tracer tests |
| 2 | af78968a | refusal matrix and the remaining tests |

Tracer feedback gate: Task 1's `<verify>` is automated only; it passed, and was re-run with the Task 2 set (all green) before the plan was considered done.

## Verification

| Command | Result |
|---|---|
| `uv run pytest -m "not docker" tests/test_margin_guard.py tests/test_symbol_config_guard.py tests/test_bracket_cache.py tests/test_margin_check.py tests/test_liquidation_price.py` | passed |
| `uv run pytest -m "not docker" tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py tests/test_phase21_gate.py tests/test_live_risk_inputs.py tests/test_no_unratified_defaults.py` | passed |
| `uv run mypy src/execution/margin_guard.py` | Success: no issues |
| `uv run ruff check` / `ruff format --check` on the three plan files | clean |
| `git diff --exit-code -- pyproject.toml uv.lock docs/DECISIONS.md params config` | clean |
| `git log --grep="^[a-z]*(22-14):" -- config params src/adapters src/risk src/persistence src/domain` | prints nothing |

Mutation check (done by hand, source restored byte for byte afterwards): replacing `entry_fee_rate=request.fee_rate_entry` by a zero, passing `True` for the netting argument, excluding a wrong plan id and making the notional check `>=` each made the suite fail.

Evidence label: executed unit tests with the recorded Demo payloads through the real adapter (demo-observed, not mainnet) [DESIGN]. Criterion 1 is not Demo-proven (no ISOLATED answer recorded), criterion 2 is not Demo-proven (the isolated liquidation price of a not-yet-open position is unobserved beyond the 2026-10-24 G6 record) and criterion 3 is not Demo-proven (what `availableBalance` deducts is unobserved; the 2026-10-24 run observed a fall by the resting order's margin, but the constant stays False until the owner's DECISIONS row). The limits in the tests are TEST_ONLY; the owner's three margin numbers are still NOT_CONFIGURED in config.

## Deviations from Plan

### Process

**1. [Process] The module was written before the tests, so the red phase was not run**
- The module in its final form (all branches) was written first and the tracer tests then passed on their first run; Task 1 therefore already contained every branch and Task 2 added only tests. Task 2 found no defect in the module. To compensate, the four hand mutations above were run against the finished tests.

### Auto-fixed Issues

None in scope. Small choices inside the plan's latitude:

- `ClaimsPort.list_margin_claims` also accepts an awaitable result.
- The test numeric-literal guard allows 0 and 1 (comparisons such as `leverage < 1`); no limit, rate, bracket or leverage value exists in the module.
- Two `# type: ignore[attr-defined]` in the test file for reading `liquidation_verdict` and the netting constant off the module (patched by name); `uv run mypy` on test files is not a gate (src only).

## Known Stubs

None. The guard is a library; nothing composes it into a running process before plan 22-15 (manager) and Phase 24, and live placement stays disabled.

## Threat Flags

None. No new endpoint, auth path, file access or storage; no logging; no dependency change. T-22-48 (modes and unreadable readings refused first with zero configuration calls), T-22-49 (verified leverage only, reading re-judged after the last await, bracket reading re-checked, virtual-clock ageing test), T-22-50 (code table, order test with spies), T-22-51 (class-name-only, message-bearing exception tests, capture_logs) and T-22-52 (construction refusal, AST literal test) are mitigated as planned.

## Self-Check: PASSED

- src/execution/margin_guard.py, tests/support/margin_guard_fakes.py, tests/test_margin_guard.py exist.
- Commits e2b63617 and af78968a are ancestors of HEAD.
