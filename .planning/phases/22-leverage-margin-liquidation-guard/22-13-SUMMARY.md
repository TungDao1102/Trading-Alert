---
phase: 22-leverage-margin-liquidation-guard
plan: 13
subsystem: execution
tags: [liquidation, post-fill, protection-coordinator, close-required, fail-closed, O-4, F-964, D-12]
requires:
  - phase: 22
    provides: "src/risk/liquidation.py with the required entry_fee_rate (plan 22-07 and its 2026-10-24 amendment); margin.liquidation_buffer_bps limit (plan 22-02); the BracketCache shape (plan 22-12)"
provides:
  - "src/execution/liquidation_watch.py: LiquidationFailurePolicy, LiquidationWatchAction, LiquidationWatchInput, LiquidationWatchVerdict, LiquidationWatchPort, BracketSource, EntryFeeRateSource, LiquidationWatch, the codes LIQUIDATION_UNKNOWN_AFTER_FILL, LIQUIDATION_TOO_CLOSE_AFTER_FILL, LIQUIDATION_PRICE_DIFFERS"
  - "src/execution/protection.py: optional liquidation_watch argument (default None), _Tracked.liquidation_checked, _check_liquidation_once, BRANCH_B6_LIQUIDATION_TOO_CLOSE, ALERT_LIQUIDATION_DIVERGENCE, four liquidation journal events"
  - "tests/support/protection_doubles.py: make_rig(liquidation_watch=...) pass-through"
affects: [22-14, 22-15, 22-16, 24]
tech-stack:
  added: []
  patterns: ["optional injected port with default None leaves every earlier caller and journal unchanged", "required enum policy argument without default (FundingPolicy precedent) for an open owner decision"]
key-files:
  created:
    - src/execution/liquidation_watch.py
    - tests/test_liquidation_watch.py
    - tests/test_protection_liquidation.py
  modified:
    - src/execution/protection.py
    - tests/support/protection_doubles.py
key-decisions:
  - "The exchange liquidationPrice decides; None, zero, negative and non-finite values are UNKNOWN and fail closed (Pitfall 7). The local price only calibrates and never turns a pass into a failure."
  - "The entry fee rate comes from a port (EntryFeeRateSource) given to the watch as a required fee_rates= argument; None or an error from it, or from the bracket source, skips only the local comparison."
  - "'Differs' = unequal at the decimal places of the exchange's own string (local rounded half-up to it); no tolerance number is chosen."
  - "A watch that raises, a verdict of the wrong type or a position row the input cannot be built from is a CLOSE through the coordinator (fail closed)."
status: complete
requirements-addressed: [EXEC-02, RISK-02]
duration: ~90 min
completed: 2026-10-24
commits: 7
plan_head_before: 6fd5debab9bfebe8319be640d68fe5e61b068492
plan_head_after: dde2f039b4dd7f8c4e76981c1b260ceda569839d
actuals:
  tokens: 13800
  tasks: 2
  commits: 2
---

# Phase 22 Plan 13: Post-fill liquidation watch Summary

**After the first fill and once the stop is REST-confirmed, an optional, once-per-plan check compares the exchange's own `liquidationPrice` with the strict D-09 buffer predicate (measured from the actual fill price) and with the locally computed price; a danger or an unknown value (None, "0") goes through the existing CLOSE_REQUIRED path as branch B6, and the close-or-alert choice (O-4) is a required constructor argument of the watch with no default.**

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 (tracer) | b883e415 | `liquidation_watch.py` and `tests/test_liquidation_watch.py`: judgement, unknown matrix, required policy, purity AST tests |
| 2 | dde2f039 | coordinator hook, `B6_LIQUIDATION_TOO_CLOSE`, events, `make_rig` pass-through, `tests/test_protection_liquidation.py` |

`commits: 7` is the measured `rev-list` count from the ledger base; the tree is shared with the wave-3 siblings (22-10, 22-11, 22-12), so five of the seven are not mine. `actuals.commits: 2` counts this plan's own commits. `actuals.tokens` is chars/4 over this plan's added lines. The SUMMARY commit follows.

## What was built

- `LiquidationWatch(brackets=, fee_rates=, limits=, policy=)`. Construction raises `ExecutionLimitsNotConfigured` naming `margin.liquidation_buffer_bps` while it is unset, and `TypeError` for a policy that is not a `LiquidationFailurePolicy` member (also when omitted: no default).
- `check(inputs)`: unknown (exchange value None/zero/negative/non-finite, leverage None or below one, inverted stop geometry) is `CLOSE` or `ALERT_ONLY_FAILED` by policy with `LIQUIDATION_UNKNOWN_AFTER_FILL`; a value that fails `liquidation_beyond_stop` (strict, from the actual fill price, buffer from the limit) likewise with `LIQUIDATION_TOO_CLOSE_AFTER_FILL`; a pass is `OK` (equal at the exchange's decimal places, or local price unavailable) or `OK_DIFFERS`. Both exact prices are on the verdict.
- Local price: `liquidation_price(..., entry_fee_rate=...)` from the bracket reading and the fee port. Golden G6 is reproduced through the watch: exchange 64968.85373637 vs local 64968.853735 is `OK_DIFFERS` (within 1e-5); the same local value against the coarser string 64968.85 is `OK`.
- Coordinator: `_check_liquidation_once` runs at the top of the PROTECTED_ENTRY_OPEN, PROTECTED, COMPLETE and TP_UNAVAILABLE branches of `_step_plan` (after REST confirmation, before the supervision of that step), reads the positions once with the same guarded call as `_position_is_open`, builds the input from the row and the `RestingEntry` (stop, leverage of the plan constraint snapshot), and calls the watch once. CLOSE -> `_enter_close_required(tracked, BRANCH_B6_LIQUIDATION_TOO_CLOSE)` (SAFE_MODE CLOSE_REQUIRED once, critical alert, one emergency close, stop kept, nothing else sent). OK -> `PROTECTION_LIQUIDATION_CHECKED`. OK_DIFFERS -> `PROTECTION_LIQUIDATION_PRICE_DIFFERS` with both prices plus one `DIVERGENCE` alert `LIQUIDATION_PRICE_DIFFERS`. ALERT_ONLY_FAILED -> `PROTECTION_LIQUIDATION_FAILED_ALERT_ONLY` plus one `DIVERGENCE` alert. No state, transition, deadline or stop-placement change.
- Tests over the Phase 19 fake exchange: CLOSE with the scripted closer (state CLOSE_FAILED after the unchanged close flow, B6 edge from PROTECTED, closer once, no `cancel_algo_order`, no extra placement) and with the real closer (one reduce-only MARKET close, flat); input built from the row; OK once and never again; OK_DIFFERS exact prices and no digit in the alert reason; ALERT_ONLY no close; raising watch, wrong verdict type, unreadable read retried, flat read, not before the stop is confirmed, PROTECTED_ENTRY_OPEN, the recorded sentinel texts None / "0" / "0.00000000" through the real watch; identical stop payloads and transitions with and without a watch; identical journal with `None`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Fee rate port.**
- **Found during:** Task 1 (plan_check_addenda).
- **Issue:** `liquidation_price` now requires `entry_fee_rate`; the plan's constructor `LiquidationWatch(brackets=, limits=, policy=)` and `LiquidationWatchInput` carry no fee, and the coordinator has no fee.
- **Fix:** a required `fee_rates=` argument (`EntryFeeRateSource.entry_fee_rate(*, symbol) -> Decimal | None`). No constant in `src/execution` or `src/risk`. Phase 24 composition / plan 22-14 decide where the rate comes from; `None` or an exception skips only the local comparison.
- **Files modified:** src/execution/liquidation_watch.py
- **Commit:** b883e415

**2. [Rule 1 - Bug avoided] Hook also runs in COMPLETE and TP_UNAVAILABLE.**
- **Found during:** Task 2 (the "unreadable read is retried" test).
- **Issue:** the PROTECTED step that fails to read the position still attaches the take-profits and moves the plan to COMPLETE in the same step, so a hook limited to PROTECTED_ENTRY_OPEN and PROTECTED would never retry (and a plan restored already in COMPLETE would never be checked).
- **Fix:** the same once-per-plan call at the top of the COMPLETE / TP_UNAVAILABLE branch. It runs only while the plan is unchecked, so a normal run is unchanged.
- **Commit:** dde2f039

**3. [Judgement] Failure inside the coordinator.** A watch that raises, a wrong verdict type or a row the input cannot be built from is a CLOSE regardless of the policy (the policy lives inside the watch). Under ALERT_ONLY an owner who wants never to close would still see a close in these rare error cases; stated so the owner can decide.

## Verification

- Plan tests and protection suites (`test_liquidation_watch`, `test_protection_liquidation`, `test_protection_coordinator`, `test_protection_branches`, `test_protection_demo_shapes`, `test_protection_rebuild`, `test_alert_producers`, `test_manual_controls`, `test_exchange_error_rejections`): all passed.
- Gate files (`test_phase19_gate`, `test_phase20_gate`, `test_phase21_gate`, `test_paper_shadow_isolation`): passed. `test_startup_recovery`, `test_execution_manager`, `test_execution_write_ahead_pg` (TEST_DATABASE_URL was set in the environment), `test_demo_rehearsal_flow`: passed.
- `uv run mypy src/execution/liquidation_watch.py src/execution/protection.py`: no issues. `ruff check` and `ruff format --check` on the five plan files: clean.
- `git diff --exit-code -- pyproject.toml uv.lock docs/DECISIONS.md params config`: exit 0. No 22-13 commit touches `config params src/adapters src/risk src/persistence src/domain`. No post-commit deletions.
- Line endings: `protection.py` and `protection_doubles.py` are CRLF in the working tree and were edited bytes-aware (diff shows only added lines); new files are LF.
- Evidence label: executed unit tests over the Phase 19 fake exchange [DESIGN]. The exchange's isolated `liquidationPrice` for a filled position has only one Demo record (22-DEMO-RESULTS, Demo-observed, not mainnet); the watch is built and tested but NOT composed (Phase 24 composes it, plan 22-16 records it).

## Known Stubs

None.

## Threat Flags

None. T-22-43 (sentinel "0"/None read as safe) is covered by the tested unknown matrix, also through the coordinator with the real watch. T-22-44/45: the hook adds no order, never cancels the stop, and runs only after REST confirmation; the protection suites pass unchanged. T-22-47: alert reasons are fixed codes, exact prices only in the internal journal note. T-22-SC: no dependency change.

## For the owner

- **O-4 stays open**: should a position whose exchange liquidation price is inside the buffer, or unknown, be closed (`CLOSE_POSITION`, the D-12 default) or only alerted (`ALERT_ONLY`)? Both are built behind a required argument with no default; the composition (Phase 24) passes your answer. Setting `margin.liquidation_buffer_bps` (O-2) is still needed for the watch to exist at all.
- On Demo the exchange reports `"0"` for a cross-margin position; this check treats that as unknown and closes, which is the safe reading. The isolated case is observed only once (BTC LONG, one tier).
- The entry fee rate source for the local comparison is not chosen here; until one is composed the comparison is skipped and the exchange value alone decides.

## Self-Check: PASSED

- src/execution/liquidation_watch.py, tests/test_liquidation_watch.py, tests/test_protection_liquidation.py exist; src/execution/protection.py and tests/support/protection_doubles.py are modified and committed.
- Commits b883e415 and dde2f039 exist on `develop`.
