---
phase: 22-leverage-margin-liquidation-guard
plan: 15
subsystem: execution
status: complete
tags: [margin-guard, gate-5f2, execution-manager, plan-snapshot, divergence-alert, config-journal, rehearsal, fail-closed, criterion-1, criterion-2, criterion-3, criterion-4]
requirements-addressed: [RISK-01, RISK-02, EXEC-01]
requires: [22-14]
provides:
  - "src/execution/live_context.py: required keyword margin_guard (MarginGuardPort) on LivePlacementContext"
  - "src/execution/manager.py: gate 5f2 (margin_guard.evaluate), the in-memory verified snapshot handed to RestingEntry, ALERT_DIVERGENCE, EVENT_MARGIN_CONFIG_CHANGED and the two best-effort helpers"
  - "scripts/demo_rehearsal.py: RunContext.margin_guard, build_context/main(margin_guard=), MARGIN_GUARD_NOT_COMPOSED abort"
  - "tests/support/margin_guard_stub.py: StubMarginGuard, passing_verdict, refusing_verdict"
  - "tests/test_snapshot_margin_leverage.py: the COMPLETE-snapshot test of D-05"
affects: [22-16, phase-24]
tech-stack:
  added: []
  patterns:
    - "guard between the account-state gates and the consume: a refusal costs nothing and can be retried"
    - "dataclasses.replace over the frozen context snapshot, in the same try as the RestingEntry construction"
    - "best-effort alert and journal helpers in the shape of _alert_duplicate_execution (try/except Exception, fixed codes only)"
key-files:
  created:
    - tests/support/margin_guard_stub.py
    - tests/test_snapshot_margin_leverage.py
  modified:
    - src/execution/live_context.py
    - src/execution/manager.py
    - scripts/demo_rehearsal.py
    - tests/test_execution_manager.py
    - tests/test_demo_rehearsal_flow.py
key-decisions:
  - "Gate 5f2 sits after gate 5f and before gate 5g, so the guard (which can POST an account configuration) is unreachable while live orders are disabled, a limit is NOT_CONFIGURED, SAFE_MODE is on, the account is Hedge or a position/order exists on the symbol; nothing is consumed on a refusal."
  - "The request is built from the values that are sent: bound symbol and side, sized quantity, snapped limit and stop, the gate 5e mark price, the gate 4a fee rates and flatness from the gate 5e reads. An unusable mark price, a request that raises at construction, a guard that raises and an answer that is not a MarginGuardVerdict are all NO_TRADE UNCERTAIN_ACCOUNT_STATE."
  - "The verdict's code is returned as is (INSUFFICIENT_MARGIN from the enum, the other plain strings); RejectionReason is unchanged."
  - "The verified margin type, leverage and equity replace the IN-MEMORY snapshot only; live_context.plan_constraint_snapshot (the write-once evidence) is untouched, and an invalid verified value is PROTECTION_INPUTS_INVALID."
  - "The DIVERGENCE alert goes out whenever the verdict carries an alert reason (the guard sets only MARGIN_CONFIG_UNVERIFIED); the MARGIN_CONFIG_CHANGED journal event goes out whenever config_changed is True, on a refusal and on a pass, with configuration words and numbers only."
  - "The rehearsal aborts with MARGIN_GUARD_NOT_COMPOSED in every mode when no guard is injected (composition is Phase 24)."
commits: 2
plan_head_before: 74c51864ba182d643614e7bb208790d0e54a27ec
plan_head_after: 3f535993fc500ec1aae988a872e3628bb52bbe69
actuals:
  tokens: 11700
  tasks: 2
  commits: 2
metrics:
  completed: 2026-10-24
---

# Phase 22 Plan 15: Margin guard in front of the entry Summary

**`execute_approved_plan` now judges every approved plan with the Phase 22 guard at gate 5f2, after the position mode and before anything is consumed; a pass completes the in-memory plan snapshot handed to the protection coordinator with the exchange-verified ISOLATED, leverage and Phase 21 equity, and a refusal returns the guard's plain code and leaves the approval retryable (demo-observed payloads through the real guard, not mainnet).**

## What was built

- `src/execution/live_context.py`: `margin_guard: MarginGuardPort` is a required keyword-only field before the optional `alert_sink`; `__post_init__` refuses an object without a callable `evaluate`. Docstrings explain why the guard is reached only after the enablement, limits and SAFE_MODE gates (CR-07: no `None` default).
- `src/execution/manager.py`
  - Gate 5f2 (one `margin_guard.evaluate` line, between the gate 5f block and the gate 5g comment). The `MarginGuardRequest` takes the bound symbol and side, `quantity`, `limit_price`, `sl_trigger_price`, the gate 5e mark price, `cost_rates.fee_rate_entry` and `fee_rate_exit`, and `symbol_is_flat` from `_position_symbols` and `_open_order_symbols` through the new `_symbol_is_flat` (None from either read means not flat).
  - A no-trade verdict returns `ExecutionOutcome(True, verdict.reason_code)`; every failure to build, call or read the guard returns `UNCERTAIN_ACCOUNT_STATE` (`BaseException` propagates).
  - On a pass, `verified_snapshot = replace(live_context.plan_constraint_snapshot, margin_type=, leverage=, equity_used=)` inside the same `try` as the `RestingEntry`, which receives it; a `ValueError`/`TypeError` there is `PROTECTION_INPUTS_INVALID`.
  - `ALERT_DIVERGENCE = "DIVERGENCE"` (existing OPS-05 event, `src/ops/alerts.py` unchanged), `EVENT_MARGIN_CONFIG_CHANGED`, `_journal_margin_config_changed` and `_alert_margin_divergence`; module and function docstring gate lists name gate 5f2.
- `scripts/demo_rehearsal.py`: `RunContext.margin_guard`, `build_context(margin_guard=)`, `main(margin_guard=)` (a test seam like the other injectables), `build_live_context` passes it into the context or raises `RehearsalAbort("MARGIN_GUARD_NOT_COMPOSED: ...")` right after the limits check; the `snapshot_live_inputs` comment now says it only feeds the rehearsal's own pre-guard snapshot.
- `tests/support/margin_guard_stub.py`: `StubMarginGuard(verdict=, exception=, event_log=)` recording requests, plus `passing_verdict` (ISOLATED, 5, 4999.09343961) and `refusing_verdict`.
- Tests (all green):
  - `tests/test_execution_manager.py` (+14 tests): event order `get_position_mode`, `guard.evaluate`, `place_entry`; the request compared with the `place_entry` arguments, the registry stop and the fixture rates; the golden adapter sequence unchanged; verified snapshot handed over (frozen context snapshot untouched, valid for live at the placement instant); refusal consumes nothing and the same approval places later; plain-string code passes through; raising guard (text not leaked) and unbuildable request fail closed; six earlier gates (disabled, unset limit, SAFE_MODE, Hedge, unreadable mode, position on the symbol) make zero guard calls; `margin_guard` required and callable; DIVERGENCE alert exactly once with a fixed argument set and no amount, none without an alert reason, sink or with a failing sink; MARGIN_CONFIG_CHANGED on a pass and on a refusal, none when no POST was sent, a failing journal changes nothing. The context-validation field set and bad-values table gained `margin_guard`; the live_context purity allow-list gained `src.execution.margin_guard`.
  - `tests/test_snapshot_margin_leverage.py` (6 tests): a real verdict from the plan 22-14 composite rig (recorded CROSSED x20 account to ISOLATED x5, equity 4999.09343961) makes the snapshot COMPLETE and `snapshot_is_valid_for_live` True at the capture time, at exactly the TTL and False one millisecond later; False and INCOMPLETE with `margin_type`, `leverage` or `equity_used` None; `UNKNOWN` margin type refused by construction; one full manager placement whose registry entry snapshot is valid for live while the context's own stays INCOMPLETE.
  - `tests/test_demo_rehearsal_flow.py`: `run_flow` and `make_ctx` inject a scripted passing guard by default (`None` stays expressible); new tests for a refusing guard (ABORTED_NO_ORDER), for `build_live_context` passing the guard, and for the abort without a guard (direct and through `main`).

## Task commits

| Task | Commit | Description |
|---|---|---|
| 1 (tracer) | 93fc49db | required field, gate 5f2, verified snapshot, helpers, stub, manager tests |
| 2 | 3f535993 | alert and journal tests, snapshot test, rehearsal injection and its tests |

Tracer feedback gate: Task 1's `<verify>` is automated only (`tests/test_execution_manager.py`); it passed, and the full Task 2 set (manager, snapshot, rehearsal, margin guard, gate files) was re-run green before the plan was considered done.

## Verification

| Command | Result |
|---|---|
| `uv run pytest -m "not docker" tests/test_execution_manager.py tests/test_snapshot_margin_leverage.py tests/test_snapshot_live_equity.py tests/test_demo_rehearsal_flow.py tests/test_demo_rehearsal_safety.py tests/test_margin_guard.py` | passed |
| `uv run pytest -m "not docker" tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py tests/test_phase21_gate.py tests/test_execution_gates.py tests/test_alerts.py tests/test_alerts_ops05_matrix.py tests/test_paper_shadow_isolation.py tests/test_agents_md.py tests/test_no_unratified_defaults.py` | passed |
| `uv run pytest -m "not docker" tests/test_alert_producers.py tests/test_exchange_error_rejections.py tests/test_risk_first_spill.py tests/test_execution_exactly_once_pg.py tests/test_execution_write_ahead_pg.py tests/test_intent_recovery_pg.py` (TEST_DATABASE_URL set, no skips) | passed |
| `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_execution_exactly_once_pg.py` | passed |
| `uv run mypy src/execution/live_context.py src/execution/manager.py` | Success: no issues |
| `uv run ruff check` / `ruff format --check` on the eight plan files | clean |
| `git diff --exit-code -- pyproject.toml uv.lock docs/DECISIONS.md params config src/ops/alerts.py` | clean |
| `git log --grep="^[a-z]*(22-15):" -- src/adapters src/risk src/persistence src/domain params config` | prints nothing |

The full suite was not run (the orchestrator runs it once per phase). Line endings were kept (working-tree CRLF for manager.py, live_context.py, demo_rehearsal.py and the two edited test files; edits were bytes-aware).

Evidence label: executed unit tests with stubs and the real guard over recorded Demo payloads (demo-observed, not mainnet) [DESIGN]. Nothing runs in a process (Phase 24 composes), live placement stays disabled, and EXEC-01 and EXEC-02 stay Pending; no requirement is marked complete here (plan 22-16 records the status).

## Deviations from Plan

### Process

**1. [Process] The alert and journal helpers shipped with the gate, their tests with Task 2**
- The helpers `_journal_margin_config_changed` and `_alert_margin_divergence` and their calls are part of the gate 5f2 block, so they are in the Task 1 commit (93fc49db); their tests are in the Task 2 commit. The red phase was run for the required field (the whole manager suite failed on the unknown `margin_guard` keyword before the implementation), not separately for the helpers.

### Plan-text adjustments

**2. [Rule 3 - blocking] `main()` gained a `margin_guard` test seam**
- The rehearsal tests drive the run through `dr.main(...)`, which builds the context itself, so the plan's `build_context` argument alone could not reach it. `main(margin_guard=)` forwards it (default `None`, no CLI flag).

**3. [Plan reading] The no-guard abort applies in every mode, not only an executed run**
- A `LivePlacementContext` cannot be built without a guard, and inventing a passing dry-run guard would hide the missing composition (T-22-56). Dry runs with committed limits already abort at the limits step, so no reachable behavior changes today.

**4. [Deliberate pin update] The rehearsal "known gap" test now asserts the new behavior**
- `test_fill_scenario_with_the_incomplete_snapshot_is_tp_unavailable_a_known_gap` could not keep its expectation: with a passing guard the snapshot handed to protection is COMPLETE, so the run places the stop and both take-profits and ends COMPLETE (G4-039 closed for the live path). It was rewritten as `test_fill_scenario_the_margin_guard_closes_the_incomplete_snapshot_gap` (stop, TP1, TP2, final state COMPLETE; the rehearsal's own recorded `plan_snapshot_status` is still INCOMPLETE). The refusal of an INCOMPLETE snapshot itself stays pinned in the protection coordinator tests; nothing was weakened there.

**5. [Test technique] The unbuildable-request case is driven by patching `manager.MarginGuardRequest`**
- A non-positive mark price in the fake reading is refused earlier by gate 5e (`MARK_PRICE_UNAVAILABLE`), so it cannot reach gate 5f2. The branch (request construction raises, guard not called, nothing consumed) is proven by monkeypatching the request class to raise `ValueError`. The manager also raises inside the same `try` when the gate 5e mark price is unusable.

**6. [No change needed]** `tests/test_demo_rehearsal_safety.py`, `tests/test_snapshot_live_equity.py`, `tests/test_phase19_gate.py` and `tests/test_phase20_gate.py` needed no edit (they passed unchanged); only the `live_context` purity allow-list in `tests/test_execution_manager.py` gained the new import.

### Auto-fixed Issues

None.

## Known Stubs

None. `StubMarginGuard` is TEST_ONLY test support; the production guard is `src/execution/margin_guard.py` (plan 22-14) and is composed into a process in Phase 24.

## Threat Flags

None. No new endpoint, auth path, file access or storage; the guard POST path existed in plan 22-11 and is now reachable only through gate 5f2. T-22-53 (six earlier refusals make zero guard calls), T-22-54 (a refusal leaves no ENTRY row and the approval places later), T-22-55 (request compared with the place_entry arguments), T-22-56 (required field, callable check, rehearsal abort), T-22-57 (journal evidence, fixed-code alert, no amount) and T-22-58 (replace only from the verdict, invalid value is PROTECTION_INPUTS_INVALID, context snapshot untouched) are mitigated as planned. T-22-SC: no dependency change.

## For the owner

An executed rehearsal needs the Phase 24 composition of the guard. `scripts/demo_rehearsal.py` has no way to build the live `MarginGuard` today (adapter, `LiveEquitySource`, `SymbolConfigGuard`, `BracketCache`, claims reader and the three owner margin numbers), so an executed run stops at `MARGIN_GUARD_NOT_COMPOSED` once the limits are set. While `margin.liquidation_buffer_bps`, `margin.max_bracket_age_ms` and `margin.headroom_bps` are NOT_CONFIGURED it stops earlier, at the limits step. Nothing was sent to Binance by this plan. Live placement remains disabled.

## Self-Check: PASSED

- src/execution/live_context.py, src/execution/manager.py, scripts/demo_rehearsal.py, tests/support/margin_guard_stub.py, tests/test_snapshot_margin_leverage.py, tests/test_execution_manager.py and tests/test_demo_rehearsal_flow.py exist and are modified or created as listed.
- Commits 93fc49db and 3f535993 are ancestors of HEAD.
