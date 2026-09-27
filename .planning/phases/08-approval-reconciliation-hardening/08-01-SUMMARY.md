---
phase: 08-approval-reconciliation-hardening
plan: "01"
subsystem: approval-core
tags: [tdd, tracer, approval, replay, idempotency, binding-gate]
dependency_graph:
  requires: []
  provides:
    - src/approval/tokens.py
    - src/approval/binding.py
    - src/approval/replay.py
    - tests/test_approval_replay.py
    - tests/fixtures/phase8/replay_5x/
  affects:
    - APRV-02
tech-stack:
  added: []
  patterns:
    - pure-core dependency-free package (stdlib + src/domain/* only)
    - fixed-order binding gate (chat -> expiry -> plan-hash -> version -> token)
    - token-hash idempotency key with constant-time compare
    - replay-to-existing semantics (5x replay = 1 transition)
    - WR-07 PENDING iff acted_at_utc None re-checked at transition
key-files:
  created:
    - src/approval/__init__.py
    - src/approval/tokens.py
    - src/approval/binding.py
    - src/approval/replay.py
    - tests/test_approval_replay.py
    - tests/fixtures/phase8/replay_5x/input.json
    - tests/fixtures/phase8/replay_5x/expected.json
  modified: []
decisions:
  - "D-01 fixed gate order enforced: chat -> expiry -> plan-hash -> version/parameter-set -> token; chat gate runs BEFORE any state lookup (security-critical invariant)"
  - "D-02 token-hash is the idempotency key; raw token never persisted or logged; SHA-256 hex form stored on Approval.approval_token_hash"
  - "D-03 constant-time compare via hmac.compare_digest prevents timing attacks on token verification"
  - "D-04 expiry boundary inclusive: now_utc >= expiry_utc is expired; one second before expiry is still approvable"
  - "D-05 resolve_callback accepts binding context (authorized_chat_id, expiry_utc, identity tuple) as kwargs; lookup and save are caller-supplied callables (dependency injection — replay layer never touches DB)"
  - "D-06 ApprovalRejected exception carries canonical RejectionReason; no synonym reason strings invented outside src/domain/enums.py"
  - "D-07 notify-failure path: save() raises -> approval stays PENDING, no transition persisted (WR-07 invariant preserved)"
  - "D-08 action_to_result mapping: APPROVE -> APPROVED, SKIP_USER/SKIP_BUSY/CANCEL -> SKIPPED, SIMULATE -> PENDING (SIMULATE is notify-only, never reaches replay)"
metrics:
  duration: "~15 min"
  completed_date: "2026-09-27"
  tasks: 3
  commits: 3
  tests_added: 13
  tests_passing: 13
  full_suite_regressions: 0
status: complete
actuals:
  tokens: 18500
  tasks: 3
  commits: 3
---

# Phase 8 Plan 01: Approval Binding + Replay Tracer Slice Summary

## One-liner

Pure approval state machine (issue token, bind callback to plan identity, resolve replay to existing approval) with 5x-replay proof and full refusal matrix — stdlib + src/domain/* only, zero forbidden imports.

## What was built

### `src/approval/tokens.py` — one-time token primitives
- `issue_one_time_token()` — `secrets.token_urlsafe(32)` returns a 43-char URL-safe string
- `token_hash_of(raw_token)` — SHA-256 hex digest (64-char lowercase hex)
- `verify_token_hash(raw_token, expected_hash)` — `hmac.compare_digest` constant-time compare

### `src/approval/binding.py` — callback payload + fixed-order gate
- `Callback` frozen dataclass — raw_token, chat_id, plan_hash, strategy_version, parameter_set_id, parameter_set_hash, callback_at_utc
- `BindingCheck` frozen dataclass — ok, reason_code
- `ApprovalRejected` exception — carries canonical RejectionReason
- `action_to_result(action)` — APPROVE -> APPROVED, SKIP_USER/SKIP_BUSY/CANCEL -> SKIPPED, SIMULATE -> PENDING
- `check_binding_full(...)` — fixed-order gate: chat -> expiry -> plan-hash -> version/parameter-set -> token

### `src/approval/replay.py` — replay-to-existing resolution
- `resolve_callback(callback, lookup_by_token_hash, save, *, authorized_chat_id, expiry_utc, approval_strategy_version, approval_parameter_set_id, approval_parameter_set_hash, now_utc=None)` — chat gate first, then token-hash lookup, then binding check, then exactly-one transition (PENDING -> decided) or replay-to-existing return

### `tests/test_approval_replay.py` — 13 tests
- Beh. 1a-c: token primitives (issue, hash, verify)
- Beh. 2: 5x replay proof (exactly one transition)
- Beh. 3: expired plan -> APPROVAL_EXPIRED
- Beh. 4: plan-hash mismatch -> STALE_SETUP
- Beh. 5: version mismatch -> INVALIDATED
- Beh. 6: wrong chat rejected BEFORE state lookup
- Beh. 7: wrong token rejected
- Beh. 8a: exactly-at-expiry unapprovable
- Beh. 8b: one second before expiry approvable
- Beh. 9: notify-failure leaves approval PENDING
- Beh. 10: no synonym reason strings in src/approval/

### `tests/fixtures/phase8/replay_5x/{input,expected}.json` — golden replay pair
- input.json: approval_id, trade_plan_id, signal_id, chat_id, action, raw_token, token_hash (SHA-256 of raw_token), plan_hash, strategy_version, parameter_set_id, parameter_set_hash, requested_at_utc, expiry_utc, callback_at_utc, replay_count=5
- expected.json: transitions_count=1, final_status=APPROVED, final_result=APPROVED, acted_at_utc, approval_token_hash, replay_returns_existing=true

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed fixture token_hash mismatch**
- **Found during:** Task 1 GREEN
- **Issue:** The fixture's `token_hash` was a hardcoded placeholder that didn't match the actual SHA-256 of `raw_token`. The lookup-by-token-hash returned None, causing all replay tests to fail with "approval not found".
- **Fix:** Computed the actual SHA-256 of the raw_token (`23ee06e9c72aca106698a9ae20b7d6ddf475966ba21726cabeb0d793d51c5cc1`) and updated both `input.json` and `expected.json`.
- **Files modified:** tests/fixtures/phase8/replay_5x/input.json, tests/fixtures/phase8/replay_5x/expected.json
- **Commit:** 41dfd11

**2. [Rule 1 - Bug] Fixed chat gate running after token lookup**
- **Found during:** Task 1 GREEN
- **Issue:** The wrong-chat test expected the chat gate to run BEFORE any state lookup (D-01 security invariant), but the initial implementation ran the token lookup first. This violated the "wrong chat must never touch the approval row" requirement.
- **Fix:** Moved the chat gate to the top of `resolve_callback`, before `token_hash_of` and `lookup_by_token_hash`. The binding check's chat gate is now redundant for the replay path but kept for the standalone `check_binding_full` API.
- **Files modified:** src/approval/replay.py
- **Commit:** 41dfd11

**3. [Rule 3 - Blocking] Fixed ruff findings (UP037, B017, B007)**
- **Found during:** Task 3
- **Issue:** Ruff reported 5 findings: 2x UP037 (quoted type annotations), 2x B017 (blind `pytest.raises(Exception)`), 1x B007 (unused loop variable).
- **Fix:** Removed quotes from type annotations, replaced `pytest.raises(Exception)` with `pytest.raises(ApprovalRejected)`, renamed unused loop variable to `_line_num`.
- **Files modified:** src/approval/binding.py, src/approval/replay.py, tests/test_approval_replay.py
- **Commit:** 400e4d6

### Plan Adjustments

**1. Combined Task 1 and Task 2 test files**
- **Reason:** The plan specified Task 1 as the tracer slice (5x replay proof) and Task 2 as the refusal matrix. Both were written into the same test file (`tests/test_approval_replay.py`) because the refusal tests share the same fixture and helper functions. The refusal tests were committed in Task 1's commit (41dfd11) along with the tracer, and Task 2's commit (4b65007) added only the synonym-grep guard test.
- **Impact:** No functional change; the refusal matrix is fully covered and all 13 tests pass.

## Verification Evidence

- `uv run --python 3.13 pytest tests/test_approval_replay.py -q` — 13 passed in 0.10s
- `uv run --python 3.13 pytest tests/ --ignore=tests/test_paper_ws_connect.py --ignore=tests/test_paper_supervisor_backfill.py --tb=no` — 471 passed, 5 skipped, 0 regressions
- `uv run --python 3.13 ruff check src/approval/__init__.py src/approval/tokens.py src/approval/binding.py src/approval/replay.py tests/test_approval_replay.py` — All checks passed
- `uv run --python 3.13 mypy src/approval/` — Success: no issues found in 4 source files
- Purity grep: zero forbidden imports (telegram, binance_sdk, sqlalchemy, pydantic, polars) and zero `float(` usage in src/approval/

## Threat Model Coverage

| Threat ID | Category | Mitigation | Status |
|-----------|----------|------------|--------|
| T-8-01 | Spoofing | Token-hash idempotency key + WR-07 compare-and-set; replay returns existing state, never a new transition | Implemented + tested (5x replay = 1 transition) |
| T-8-02 | Tampering | Callback-time re-check of expiry + plan hash + version with APPROVAL_EXPIRED/STALE_SETUP/INVALIDATED reason codes | Implemented + tested (Beh. 3, 4, 5, 8a) |
| T-8-03 | Information disclosure | Raw token never persisted or logged; structured logs carry hash prefix at most | Implemented (token_hash_of is the only persisted form) |
| T-8-04 | Elevation of privilege | Authorized-chat check runs first, before any state lookup (gate order fixed) | Implemented + tested (Beh. 6) |
| T-8-SC | Tampering | stdlib only (no package installs) | Accepted (no new packages) |

## Next Steps

- Plan 08-02: Telegram intake — wire the callback handler to `resolve_callback` with the binding context derived from the TradePlan/Signal lookup
- Plan 08-03: (if exists) — approval persistence layer (DB-backed lookup/save)
- Plan 08-04: Reconciler — orphan-sweeper for stale approvals
- Plan 08-05: Drills — end-to-end approval flow with Telegram fakes

## Self-Check: PASSED

- [x] src/approval/__init__.py exists
- [x] src/approval/tokens.py exists
- [x] src/approval/binding.py exists
- [x] src/approval/replay.py exists
- [x] tests/test_approval_replay.py exists
- [x] tests/fixtures/phase8/replay_5x/input.json exists
- [x] tests/fixtures/phase8/replay_5x/expected.json exists
- [x] Commit 41dfd11 exists (tracer slice)
- [x] Commit 4b65007 exists (refusal matrix)
- [x] Commit 400e4d6 exists (static gates)
- [x] 13 tests pass
- [x] Full suite: 471 passed, 5 skipped, 0 regressions
- [x] Ruff clean
- [x] Mypy strict clean
- [x] Purity grep clean
