---
phase: 08-approval-reconciliation-hardening
plan: "03"
subsystem: execution-core
tags: [tdd, tracer, execution, order-ids, determinism, idempotency]
dependency_graph:
  requires: []
  provides:
    - src/execution/order_ids.py
    - tests/test_order_ids.py
    - tests/fixtures/phase8/order_ids/
  affects:
    - EXEC-03
tech-stack:
  added: []
  patterns:
    - pure-core dependency-free package (stdlib + src/domain/enums.py only)
    - canonical ROLE_CODES table as single import site for role codes
    - fixed-shape ASCII IDs (36 chars) matching Binance client-order-ID rule
    - pure-function derivation over (plan_hash, role) — no float, no locale
    - retry/restart/replay determinism proven via importlib.reload + interleaving
key-files:
  created:
    - src/execution/__init__.py
    - src/execution/order_ids.py
    - tests/test_order_ids.py
    - tests/fixtures/phase8/order_ids/input.json
    - tests/fixtures/phase8/order_ids/expected.json
  modified: []
decisions:
  - "D-01 ROLE_CODES maps exactly the OrderRole vocabulary (ENTRY, STOP_LOSS, TAKE_PROFIT_1, TAKE_PROFIT_2) to distinct 2-char codes (EN, SL, T1, T2); the table is the only place role-code literals appear"
  - "D-02 derive_client_order_id and derive_algo_client_id are pure functions of (plan_hash, role) using stdlib only — no float, no locale-dependent string conversion"
  - "D-03 Pinned ID shape: client_order_id = 'x-' (2) + plan_hash[:32] (32) + role_code (2) = 36 chars; algo_client_id = 'xa-' (3) + plan_hash[:31] (31) + role_code (2) = 36 chars"
  - "D-04 Charset is a strict subset of the Binance client-order-ID rule (<=36 chars, ASCII alnum + hyphen/underscore): [0-9a-f-] plus uppercase role codes"
  - "D-05 Unknown role raises ValueError with the canonical vocabulary listed in the message — no fallback code, no silent default"
  - "D-06 plan_hash slice is the first N hex chars of the canonical 64-char SHA-256 plan hash — deterministic across processes and Python versions"
  - "D-07 Retry/restart/replay determinism proven: same call twice, importlib.reload, and interleaving other plans all yield byte-identical IDs"
metrics:
  duration: "~10 min"
  completed_date: "2026-09-27"
  tasks: 2
  commits: 2
  tests_added: 21
  tests_passing: 21
  full_suite_regressions: 0
status: complete
actuals:
  tokens: 18500
  tasks: 2
  commits: 2
---

# Phase 8 Plan 03: Deterministic Client/Algo Order IDs Summary

## One-liner

Pure deterministic client/algo order identifier derivation (per D-04) — ROLE_CODES canonical table + `derive_client_order_id` + `derive_algo_client_id` with retry/restart/replay proof and Binance charset/length gate — stdlib + `src/domain/enums.py` only, zero forbidden imports.

## What was built

### `src/execution/__init__.py` — package surface
- Re-exports `ROLE_CODES`, `derive_client_order_id`, `derive_algo_client_id`
- Documents the dependency-free contract (stdlib + `src/domain/enums.py` only)

### `src/execution/order_ids.py` — canonical role table + derivation
- `ROLE_CODES` — canonical role-to-code table mapping OrderRole values to 2-char codes:
  - `ENTRY` → `EN`
  - `STOP_LOSS` → `SL`
  - `TAKE_PROFIT_1` → `T1`
  - `TAKE_PROFIT_2` → `T2`
- `derive_client_order_id(plan_hash, role)` — returns `"x-" + plan_hash[:32] + role_code` (36 chars)
- `derive_algo_client_id(plan_hash, role)` — returns `"xa-" + plan_hash[:31] + role_code` (36 chars)
- `_require_plan_hash` / `_require_role` — boundary validation (TypeError for non-string, ValueError for empty/unknown)
- Pinned ID shape documented in module docstring (re-verified against installed Binance SDK)

### `tests/test_order_ids.py` — 21 tests
- Beh. 1a-b: fixed-length ASCII string (36 chars, Binance charset)
- Beh. 2a-b: determinism (same inputs → same output, byte-identical)
- Beh. 3a-c: four roles yield four distinct IDs; client/algo never collide for same role
- Beh. 4a-e: unknown role / empty role / non-string role / non-string plan_hash / empty plan_hash all raise
- Beh. 5a-b: golden fixture vectors match derivation output
- Beh. 6: different plan_hashes yield different IDs
- Beh. 7: ROLE_CODES covers exactly the OrderRole vocabulary
- Beh. 8 (retry): same call twice yields byte-identical IDs
- Beh. 9 (restart): `importlib.reload` yields byte-identical IDs
- Beh. 10 (replay): interleaving other plans does not perturb IDs
- Beh. 11 (static gate): no forbidden imports in `src/execution/order_ids.py`
- Beh. 12 (static gate): pinned ID shape matches Binance client-order-ID rule

### `tests/fixtures/phase8/order_ids/{input,expected}.json` — golden ID vectors
- `input.json`: plan_hash + four roles
- `expected.json`: client_order_ids + algo_client_ids for all four roles, id_length=36, charset

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed charset test to include uppercase letters**
- **Found during:** Task 1 GREEN
- **Issue:** The initial charset test used `set("0123456789abcdef-")` which excluded uppercase letters. The role codes (`EN`, `SL`, `T1`, `T2`) contain uppercase letters, so the test failed.
- **Fix:** Updated the charset to include all ASCII letters (upper/lower), digits, hyphen, and underscore — matching the Binance client-order-ID rule.
- **Files modified:** tests/test_order_ids.py
- **Commit:** 8e87b5d

**2. [Rule 1 - Bug] Fixed walrus operator syntax error**
- **Found during:** Task 2 GREEN
- **Issue:** A walrus operator `:=` was used inside an `assert` statement in a way that Python's parser rejected.
- **Fix:** Removed the unnecessary sanity-check line; the pattern object is already validated by the subsequent `match()` calls.
- **Files modified:** tests/test_order_ids.py
- **Commit:** 5b1ae1c

## Verification Evidence

- `uv run --python 3.13 pytest tests/test_order_ids.py -q` — 21 passed in 0.07s
- `uv run --python 3.13 pytest tests/ --ignore=tests/test_paper_ws_connect.py --ignore=tests/test_paper_supervisor_backfill.py --tb=no` — 488 passed, 5 skipped, 0 regressions
- `uv run --python 3.13 ruff check src/execution/__init__.py src/execution/order_ids.py tests/test_order_ids.py` — All checks passed
- `uv run --python 3.13 mypy src/execution/` — Success: no issues found in 2 source files
- Purity grep: zero forbidden imports (float, telegram, binance_sdk, sqlalchemy, pydantic, polars, structlog) in `src/execution/`

## Threat Model Coverage

| Threat ID | Category | Mitigation | Status |
|-----------|----------|------------|--------|
| T-8-20 | Repudiation | Deterministic IDs make retries idempotent exchange-side; blind retry without ID reuse is impossible by construction (D-04) | Implemented + tested (Beh. 8, 9, 10) |
| T-8-21 | Tampering | One canonical ROLE_CODES table; unknown roles raise ValueError; ROLE_CODES vocabulary lock test (Beh. 7) | Implemented + tested |
| T-8-22 | Denial of service | Charset/length pinned against Binance client-order-ID rule (<=36 chars, ASCII alnum + hyphen/underscore); derivation is fixed-length ASCII | Implemented + tested (Beh. 1, 12) |
| T-8-SC | Tampering | stdlib only (no package installs) | Accepted (no new packages) |

## Next Steps

- Plan 08-04: Reconciler — orphan-sweeper for stale approvals (uses ROLE_CODES from this plan)
- Plan 08-05: Drills — end-to-end approval flow with Telegram fakes

## Self-Check: PASSED

- [x] src/execution/__init__.py exists
- [x] src/execution/order_ids.py exists
- [x] tests/test_order_ids.py exists
- [x] tests/fixtures/phase8/order_ids/input.json exists
- [x] tests/fixtures/phase8/order_ids/expected.json exists
- [x] Commit 8e87b5d exists (tracer slice)
- [x] Commit 5b1ae1c exists (retry/restart/replay acceptance + static gates)
- [x] 21 tests pass
- [x] Full suite: 488 passed, 5 skipped, 0 regressions
- [x] Ruff clean
- [x] Mypy strict clean
- [x] Purity grep clean
