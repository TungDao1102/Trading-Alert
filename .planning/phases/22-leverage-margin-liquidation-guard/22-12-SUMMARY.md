---
phase: 22-leverage-margin-liquidation-guard
plan: 12
subsystem: execution
tags: [bracket-cache, leverage-brackets, liquidation-guard, freshness, fail-closed, D-11, A8]
requires:
  - phase: 22
    provides: "plan 22-01: BinanceUsdmAdapter.leverage_brackets_snapshot, SymbolLeverageBrackets, recorded Demo bracket fixture"
  - phase: 22
    provides: "plan 22-02: ExecutionLimits.margin_max_bracket_age_ms (NOT_CONFIGURED in config), TEST_ONLY value in tests/support/execution_limits.py"
  - phase: 22
    provides: "plan 22-07: pure Bracket, brackets_are_fresh, liquidation_verdict (required entry_fee_rate after the 2026-10-24 amendment)"
provides:
  - "src/execution/bracket_cache.py: BracketPort, frozen BracketReading(symbol, brackets, observed_at_utc), BracketCache(adapter=, clock=, limits=) with async get(*, symbol), invalidate(*, symbol=None) and last_error_type"
  - "tests/support/bracket_fakes.py: ScriptedBracketAdapter, demo_table, build_bracket_adapter (real adapter over a fake SDK serving the recorded bracket model), FakeBracketRest, recorded_bracket_payload"
  - "tests/test_bracket_cache.py: 43 tests including the recorded-table tracer to the G1 value"
affects: [22-13, 22-14, 22-16]
tech-stack:
  added: []
  patterns: ["LiveEquitySource analog: clock stamped before the request and re-read after the await, failure kept as exception class name, no stale fallback, generation counter for an invalidate during a read"]
key-files:
  created:
    - src/execution/bracket_cache.py
    - tests/support/bracket_fakes.py
    - tests/test_bracket_cache.py
  modified: []
key-decisions:
  - "The bound is read only from limits.margin_max_bracket_age_ms; construction raises ExecutionLimitsNotConfigured (key margin.max_bracket_age_ms) while it is None and ValueError for a non-positive value. No numeric literal, no default; the NOT_CONFIGURED key in config stays untouched."
  - "A notionalCoef that is None or exactly Decimal(1) (1.0 included) is accepted; any other value, NaN or a non-Decimal makes the read fail (ValueError / TypeError) and the symbol has no cached reading (assumption A8)."
  - "A table for another symbol and an empty bracket tuple are failed reads as well (defence in depth on top of the adapter's own checks)."
  - "A reading that is no longer fresh when the await returns is dropped and recorded as the label StaleBracketReading (the only last_error_type value that is not an exception class name); documented in the module docstring."
  - "An invalidate that arrives during a read discards that read's result and get returns None with last_error_type None (the read itself succeeded). The generation token is global plus per symbol, so invalidating another symbol does not discard the read."
  - "No single-flight lock: two concurrent first gets of one symbol may each read once. Documented; plan 22-14 calls the cache sequentially."
  - "The fake SDK for the tracer is local to tests/support/bracket_fakes.py; tests/support/account_fakes.py is not imported (plan 22-11 edits it in the same wave)."
patterns-established:
  - "Execution-layer cache over a pure freshness predicate: the module holds no bracket value, imports no adapter or SDK (rows are converted by attribute access) and logs nothing."
requirements-completed: []
status: complete
duration: ~35 min
completed: 2026-10-24
commits: 1
plan_head_before: 457f24c30dbc6c0e0c454730a9629c93580d5c31
plan_head_after: 6fd5debab9bfebe8319be640d68fe5e61b068492
actuals:
  tokens: 7900
  tasks: 2
  commits: 1
---

# Phase 22 Plan 12: bounded-age BracketCache for the liquidation guard Summary

**`BracketCache` hands the pure liquidation guard the exchange leverage brackets only while they are younger than the owner's `margin.max_bracket_age_ms`, from at most one adapter read per refresh, and hands it nothing (None) after any failure, malformed row, foreign symbol, stale read or `notionalCoef` other than 1; the recorded Demo table reaches `liquidation_verdict` through the real adapter and gives the G1 price 64257.028112449799 (demo-observed, not mainnet).**

## Performance

- **Tasks:** 2 of 2
- **Files:** 3 created (one module, one fakes file, one test file), nothing modified
- **Tests:** 43 in `tests/test_bracket_cache.py`

## Accomplishments

- Tracer: recorded `leverage_brackets.json` -> real `BinanceUsdmAdapter` over a fake SDK -> `BracketCache.get` -> `liquidation_verdict` (LONG, entry 80000, quantity 0.01, leverage 5, stop 66000, TEST_ONLY buffer 100 bps, TEST_ONLY fee rate 0): ok, price 64257.028112449799 at 12 dp; the ten `Bracket` objects equal `demo_brackets()`; one SDK call; `observed_at_utc` equals the clock value before the request.
- Freshness boundaries pinned with a virtual clock: a second get inside the bound makes no call; at exactly the bound since `observed_at_utc` it still makes none; one microsecond later it reads once more; a backwards clock (negative age) refreshes; a read that takes exactly the bound is fresh, one millisecond more is dropped (None, nothing kept).
- Fail closed: any `Exception` from the port, a naive clock value, a malformed row (negative cum, ratio 1, floor equal to or above the cap), an empty tuple, a table for another symbol, and `notionalCoef` 1.1 / 0.9 / 0 / NaN / -1 / a float all return None, record only the class name, drop the symbol's cache (no stale fallback), and call the port once per get with no sleep. A `BaseException` propagates. A later success clears `last_error_type`.
- Per-symbol independence, `invalidate(symbol=...)` and `invalidate()`, and the discard of a read that an invalidate overtook (global and per-symbol); an invalidate of another symbol leaves the read alone.
- Purity pinned by AST tests: no wall-clock call, no import of `src.adapters`, `src.persistence`, `binance*`, `sqlalchemy`, no "USDT" string, no `float(`; `capture_logs` shows no event on success or failure.

## Task Commits

Both tasks are in one commit (see Deviations).

| Task | Commit | Description |
|------|--------|-------------|
| 1 (tracer) and 2 | 6fd5deba | `feat(22-12): bounded-age BracketCache for the exchange leverage brackets` |

## Deviations from Plan

### Process

**1. [Process] One commit for both tasks, and the tests did not run red first**
- **Found during:** whole plan
- **Issue:** the module, the fakes and the full test file were written together, so Task 1 and Task 2 were not committed separately and the red phase of the red-green cycle was not run. The tests passed on their first run.
- **Effect:** the plan's per-task commit shape is not followed (1 commit instead of 2); the code and tests are the same as two commits would have produced.
- **Files modified:** none beyond the three plan files.

### Auto-fixed Issues

**2. [Rule 1 - Bug, in my own test] `invalidate(symbol=None)` is not a bad symbol**
- **Found during:** first test run (before the commit)
- **Issue:** the bad-symbol test also expected `invalidate(symbol=None)` to raise, but None means "all symbols".
- **Fix:** the test skips `invalidate` for None. No source change.
- **Commit:** 6fd5deba

### Other notes

- The label `"StaleBracketReading"` for a read that is stale at return time is the one `last_error_type` value that is not an exception class name (the plan says only class names). It is the only way for a caller to tell this failure from "never failed"; documented in the module docstring and the decisions above.
- The plan's `files_modified` order puts the `ScriptedBracketAdapter` in `tests/support/bracket_fakes.py`; `advance_per_call` is a `timedelta` and an `on_call` hook was added so the invalidate-during-read tests can run code inside the call.

## Verification

| Check | Result |
|---|---|
| `uv run pytest -m "not docker" tests/test_bracket_cache.py tests/test_liquidation_price.py tests/test_account_equity_source.py -x` | passed (168 tests) |
| `uv run pytest -m "not docker" tests/test_phase19_gate.py tests/test_phase20_gate.py tests/test_phase21_gate.py -x` | passed |
| `uv run mypy src/execution/bracket_cache.py` | Success: no issues |
| `uv run ruff check` and `ruff format --check` on the three plan files | clean |
| `git diff --exit-code -- pyproject.toml uv.lock docs/DECISIONS.md params config` | exit 0 |
| `git log --grep="^[a-z]*(22-12):" -- config params src/adapters src/risk src/persistence src/domain` | prints nothing |

`uv run mypy` on the two test files reports pre-existing errors in `tests/support/limits.py:191` (not this plan's file); the test files themselves are clean. The project's mypy gate covers `src` only.

Evidence label: executed unit tests with the recorded Demo bracket table (demo-observed, not mainnet) [DESIGN]; mainnet brackets are read live and may differ (never a constant). The owner's bound (`margin.max_bracket_age_ms`) is still NOT_CONFIGURED in `config/execution/execution-limits-v1.toml`; tests use the TEST_ONLY value 4141 only.

## Known Stubs

None. The cache is not wired into a running process; plan 22-14 wires it and plan 22-13 uses it (stated in the module docstring).

## Threat Flags

None. The module adds no network path, no auth path and no storage; it only calls the existing adapter read through a port. T-22-40, T-22-41 and T-22-42 are mitigated by the tests named above.

## Self-Check: PASSED

- FOUND: src/execution/bracket_cache.py, tests/support/bracket_fakes.py, tests/test_bracket_cache.py
- FOUND: commit 6fd5deba (ancestor of HEAD)
