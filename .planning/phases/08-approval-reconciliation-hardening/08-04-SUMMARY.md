---
phase: 08-approval-reconciliation-hardening
plan: "04"
subsystem: reconciliation
tags: [tdd, reconciler, sweeper, safe-mode, three-source-compare, exchange-truth, cancel-only, no-place-order-invariance]
dependency_graph:
  requires:
    - src/execution/order_ids.py
    - src/domain/enums.py
    - src/domain/journal.py
    - src/paper/resync.py
    - src/risk/gating.py
  provides:
    - src/reconcile/__init__.py
    - src/reconcile/compare.py
    - src/reconcile/sweeper.py
    - src/reconcile/safe_mode.py
    - tests/test_reconcile.py
    - tests/fixtures/phase8/orphan_divergence/{input,expected}.json
    - src/adapters/binance_usdm.py (extended truth surface)
  affects:
    - EXEC-02
tech-stack:
  added: []
  patterns:
    - pure-core dependency-free package (stdlib + src/domain/* + sibling modules only)
    - three-source set-difference compare (normal orders / algo orders / positions)
    - cancel-only sweeper with authoritative position-zero verification
    - journal-first ordering (pre-image BEFORE cancel, post-image AFTER)
    - Protocol-typed adapter consumption (no SDK leakage outside src/adapters/binance_usdm.py)
    - bounded tenacity retry on adapter cancel calls (3 attempts, 30s wall-clock cap)
    - SAFE_MODE state machine composing with evaluate_risk fail-closed posture
    - 60s tick constant (FLAGGED ASSUMPTION, RECON-01 unclassified)
key-files:
  created:
    - src/reconcile/__init__.py
    - src/reconcile/compare.py
    - src/reconcile/sweeper.py
    - src/reconcile/safe_mode.py
    - tests/test_reconcile.py
    - tests/fixtures/phase8/orphan_divergence/input.json
    - tests/fixtures/phase8/orphan_divergence/expected.json
  modified:
    - src/adapters/binance_usdm.py
decisions:
  - "D-01 Five divergence kinds: ORPHAN_PROTECTIVE (sweeper target), ENTRY_WITHOUT_PROTECTIVE (SAFE_MODE trigger, never swept), UNSYNCED_NORMAL, UNSYNCED_ALGO, UNSYNCED_POSITION (each drives SAFE_MODE without cancel)"
  - "D-02 ORPHAN_PROTECTIVE classification: local algo protective (SL/TP1/TP2) with no matching local position AND no exchange position — regardless of whether the algo still matches the exchange truth (the algo is supposed to protect a position, and there is no position to protect)"
  - "D-03 Sweeper requires authoritative position-zero verification (T-8-30): two consecutive zero reads from the position_verifier callable; a single non-zero read blocks the cancel (transient-gap protection)"
  - "D-04 Sweeper uses query-by-ID-first posture (T-8-32): query_algo_order_by_client probe before cancel; not-found probe is treated as a successful prior sweep (no cancel needed)"
  - "D-05 Sweeper journals pre-image BEFORE the cancel call and post-image AFTER (D-05 extended journal-first ordering); the audit trail is the safety net"
  - "D-06 SAFE_MODE enters on any divergence (idempotent re-entry; SAFE_MODE_REENTER event when reason changes); exits only on a fresh clean three-source compare PLUS a journaled SAFE_MODE_EXIT event (Pitfall 4)"
  - "D-07 SAFE_MODE_TICK_SECONDS=60 with operator-tunable-before-soak semantics (FLAGGED ASSUMPTION, RECON-01 unclassified); 60s per RESEARCH A2 — 4H/1H swing trading has orders of magnitude of headroom for a 60s REST tick"
  - "D-08 Adapter extension is the only module importing the Binance SDK for reconciliation calls; src/reconcile/ consumes Protocol-typed surfaces (cancel_algo_order, query_algo_order_by_client, snapshot_*)"
  - "D-09 SDK 17.3.1 -> 17.4.0 delta (per RESEARCH Open Question 2): no public REST method-signature change in any of the seven reconciler methods; ALGO_UPDATE.o.rm field semantics change (Dec 2025 Algo migration) is WS-side and out of scope for the REST adapter slice"
  - "D-10 Bounded-tenacity cancel ceilings (RECONCILER_CANCEL_MAX_ATTEMPTS=3, RECONCILER_CANCEL_MAX_DELAY_SECONDS=30) mirror the notify/resync precedent; transient-only retry filter; programming errors fail closed immediately"
  - "D-11 Already-canceled-as-success posture: SDK error code -2011 (UNKNOWN_ORDER) on cancel is treated as success because the post-condition the caller wanted is satisfied (the order is gone)"
  - "D-12 Zero-amount positions filtered out of snapshot_positions: Binance semantics is position_amt == 0 means no position; including them would poison the three-source compare with phantom truth rows"
metrics:
  duration: "~25 min"
  completed_date: "2026-09-27"
  tasks: 3
  commits: 3
  tests_added: 7
  tests_passing: 7
  full_suite_regressions: 0
status: complete
actuals:
  tokens: 32000
  tasks: 3
  commits: 3
---

# Phase 8 Plan 04: Three-Source Reconciler + Cancel-Only Sweeper + SAFE_MODE Summary

## One-liner

Three-source exchange-truth safety net (D-03) with typed divergence classification, cancel-only orphan-protective sweeper, and SAFE_MODE state machine composing with `evaluate_risk` — the EXEC-02 acceptance proof: injected orphan swept with verification + journal + re-scan, divergence forces SAFE_MODE, restore path is the only exit, reconciler never places orders.

## What was built

### `src/reconcile/__init__.py` — package surface

Re-exports the canonical public API:
- `compare(...)` — three-source set-difference compare
- `CompareDiff`, `Divergence`, `OrphanProtective` — frozen dataclasses
- `DIVERGENCE_KIND_*` — five canonical divergence kind constants
- `OrphanSweeper`, `SweepOutcome`, `SweepSkip` — cancel-only sweep
- `SafeModeController`, `SafeModeVerdict`, `SAFE_MODE_TICK_SECONDS` — SAFE_MODE state machine

Documents the dependency-free contract (stdlib + `src/domain/*` + sibling modules only).

### `src/reconcile/compare.py` — three-source compare

**Five divergence kinds (canonical vocabulary):**

| Kind | Trigger | Action |
|------|---------|--------|
| `ORPHAN_PROTECTIVE` | Local algo protective (SL/TP1/TP2) + no position (local or exchange) | **Sweeper target** |
| `ENTRY_WITHOUT_PROTECTIVE` | Local ENTRY + no matching algo protective for same symbol | SAFE_MODE (never swept) |
| `UNSYNCED_NORMAL` | Local normal order with no exchange match | SAFE_MODE (never swept) |
| `UNSYNCED_ALGO` | Local algo with no exchange match (non-protective) | SAFE_MODE (never swept) |
| `UNSYNCED_POSITION` | Exchange position with no local match | SAFE_MODE (never swept) |

**Local-intent representation:** duck-typed field access (attribute OR dict). The orchestrator can pass either `LocalOrderIntent`/`LocalAlgoIntent` dataclasses or dict payloads (the test fixture format).

**Sorted output:** both `divergences` and `orphan_protectives` are sorted by `(symbol, client_algo_id, client_order_id, kind)` for deterministic downstream consumption.

### `src/reconcile/sweeper.py` — cancel-only OrphanSweeper

**Three-stage verification before any cancel:**

1. **Authoritative position-zero verification (T-8-30):** calls `position_verifier(symbol=...)` twice; BOTH reads must return zero. A single non-zero read blocks the cancel with a `SweepSkip` record carrying the `transient_position_gap` reason.

2. **Query-by-ID-first probe (T-8-32 + EXECUTION_SPEC 10):** calls `adapter.query_algo_order_by_client(client_algo_id=...)`. A `found=False` probe is treated as a successful prior sweep (no cancel needed, no error).

3. **Journal-first ordering (D-05 extended):** pre-image `JournalEvent` (with `phase: pre_cancel`) committed BEFORE the cancel call; post-image `JournalEvent` (with `phase: post_cancel`) committed AFTER.

**No place-order path exists anywhere in this module** (Pitfall 1 — never auto-place rescue protection for unprotected positions). Static guard test enforces this invariant.

### `src/reconcile/safe_mode.py` — SAFE_MODE state machine

**Enter:** on any divergence (idempotent re-entry; `SAFE_MODE_REENTER` event when reason changes; `SAFE_MODE_ENTER` event on first entry).

**Guard:** `guard_new_entries(trade_plan)` returns `SafeModeVerdict(is_no_trade=True, reason_code=RECONCILIATION_REQUIRED)` when in SAFE_MODE. The risk pipeline can compose via this guard without knowing about SAFE_MODE state.

**Exit:** `exit_safe_mode(...)` re-fetches the three truth snapshots, runs the compare, and ONLY exits when the diff is clean AND a `SAFE_MODE_EXIT` JournalEvent has been recorded. A boolean flip without both is rejected (Pitfall 4).

**Tick cadence:** `SAFE_MODE_TICK_SECONDS = 60` with documented operator-tunable-before-soak semantics (FLAGGED ASSUMPTION, RECON-01 unclassified). 60s default per RESEARCH A2 — 4H/1H swing trading has orders of magnitude of headroom for a 60s REST tick.

### `src/adapters/binance_usdm.py` (EXTEND) — reconciler truth surface

**New frozen dataclasses (no SDK leakage):**
- `OpenOrderSnapshot` — one open normal order from `current_all_open_orders`
- `OpenAlgoOrderSnapshot` — one open algo order from `current_all_algo_open_orders`
- `PositionSnapshot` — one position from `position_information_v3`
- `AlgoOrderProbe` — `query_algo_order(client_algo_id=...)` result

**New adapter methods (all verified against installed SDK 17.4.0):**
- `snapshot_open_normal_orders(symbol=None)` — wraps `current_all_open_orders`
- `snapshot_open_algo_orders(symbol=None)` — wraps `current_all_algo_open_orders`
- `snapshot_positions(symbol=None)` — wraps `position_information_v3` (zero-amount rows filtered)
- `query_algo_order_by_client(client_algo_id)` — wraps `query_algo_order`; UNKNOWN_ORDER → `found=False`
- `cancel_normal_order(symbol, orig_client_order_id)` — wraps `cancel_order`
- `cancel_algo_order(symbol, client_algo_id)` — wraps `cancel_algo_order`

**Bounded-tenacity cancel ceilings:** `RECONCILER_CANCEL_MAX_ATTEMPTS=3`, `RECONCILER_CANCEL_MAX_DELAY_SECONDS=30`. Already-canceled-as-success posture: SDK error -2011 (UNKNOWN_ORDER) is treated as success because the post-condition is satisfied.

**Module docstring records the SDK 17.3.1 → 17.4.0 delta** (per RESEARCH Open Question 2 closed): no public REST signature change in any of the seven reconciler methods; the Dec 2025 ALGO_UPDATE.o.rm field semantics change is WS-side and out of scope for the REST adapter slice.

### `tests/fixtures/phase8/orphan_divergence/{input,expected}.json` — golden divergence pair

`input.json`: local intent (ENTRY + STOP_LOSS algo for BTCUSDT, no position) + exchange truth (matching ENTRY + matching algo, no position) + position verification (two consecutive zero reads).

`expected.json`: compare result (`ORPHAN_PROTECTIVE` divergence) + sweep result (1 cancelled, 0 skipped, 2 journal events, no place-order calls).

### `tests/test_reconcile.py` — 7 tests

| Test | Behavior |
|------|----------|
| Beh. 1 | Clean compare: local intent + truth agree → `agreement=True`, zero divergences |
| Beh. 2 | Orphan protective: local SL + no position → `ORPHAN_PROTECTIVE` divergence + sweeper cancels + pre/post journal + re-scan clean |
| Beh. 3 | Divergence forces SAFE_MODE: phantom exchange position → `UNSYNCED_POSITION` divergence + SAFE_MODE entered + guard returns RECONCILIATION_REQUIRED + no cancel call |
| Beh. 4 | Entry-without-protective: ENTRY + no protective → divergence present but sweeper does NOT sweep (no orphan to cancel) |
| Beh. 5 | Transient position gap: first read non-zero + second zero → cancel blocked with `SweepSkip` reason |
| Static guard | No `new_order`/`new_algo_order`/`place_order`/`place_algo_order` token in `src/reconcile/*.py` |
| Static guard | No `binance_sdk` import in `src/reconcile/*.py` (the EXEC-02 no-place-order + SDK-isolation invariants) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Compare function initially missed ENTRY_WITHOUT_PROTECTIVE divergence kind**
- **Found during:** Task 2 GREEN
- **Issue:** The fixture scenario "entry-without-protective" did not produce a divergence under the original three-kind logic (ORPHAN_PROTECTIVE / UNSYNCED_NORMAL / UNSYNCED_POSITION). The local ENTRY matched the exchange truth and there was no position — the compare returned `agreement=True`.
- **Fix:** Added the `ENTRY_WITHOUT_PROTECTIVE` divergence kind: a local ENTRY with no matching algo protective for the same symbol. This drives SAFE_MODE but is explicitly NOT swept (Pitfall 1 — never auto-place rescue protection). The kind is documented in the compare module's divergence-kind vocabulary and re-exported from the package `__init__.py`.
- **Files modified:** src/reconcile/compare.py, src/reconcile/__init__.py
- **Commit:** 6fef291

**2. [Rule 1 - Bug] Sweeper journaled a single combined event but the spec calls for pre AND post events**
- **Found during:** Task 2 GREEN
- **Issue:** The original `_build_event` produced one JournalEvent with both pre and post fields. The D-05 extended journal-first ordering contract requires two separate events (pre BEFORE cancel, post AFTER cancel).
- **Fix:** Split into `_build_pre_image_event` (phase=pre_cancel) and `_build_post_image_event` (phase=post_cancel). Test updated to assert `len(journal.events) == 2` with distinct phases.
- **Files modified:** src/reconcile/sweeper.py, tests/test_reconcile.py
- **Commit:** 703b2a5

**3. [Rule 1 - Bug] Compare function used attribute-only field access**
- **Found during:** Task 2 GREEN
- **Issue:** The compare function read `entry.client_order_id` directly, but the test fixtures use dict-format payloads (`{'client_order_id': '...'}`). The compare layer is the boundary between the orchestrator's local-intent representation and the exchange-truth snapshots — duck-typed access is required.
- **Fix:** Added `_get_field(entry, field_name)` helper that reads attribute OR dict key. Used throughout the compare function.
- **Files modified:** src/reconcile/compare.py
- **Commit:** 703b2a5

**4. [Rule 3 - Blocking] Ruff reported 10 findings on first pass (unused imports, sort order, line length, E402)**
- **Found during:** Task 2 final lint
- **Issue:** Several ruff findings across the new modules: unsorted imports in `__init__.py` and `compare.py`, unused `ROLE_CODES` import, unused `truth_position_keys` variable, E402 module-level import not at top in `safe_mode.py`, E501 line-too-long in `sweeper.py`, unused `timedelta` in `tests/test_reconcile.py`.
- **Fix:** Auto-fixed with `ruff check --fix` for the import-order issues, then manually removed the unused import, unused variable, the late `_timedelta` import (moved to top), and split the long `journal_event_id` f-string into two lines.
- **Files modified:** src/reconcile/__init__.py, src/reconcile/compare.py, src/reconcile/safe_mode.py, src/reconcile/sweeper.py, tests/test_reconcile.py
- **Commit:** 703b2a5

**5. [Rule 3 - Blocking] Mypy reported `Returning Any from function declared to return "bool"`**
- **Found during:** Task 3 final lint
- **Issue:** `_is_zero_like(value)` had `return value == 0` whose result was inferred as `Any` (because `value: Any`), failing mypy strict.
- **Fix:** Annotated the local with `result: bool` so mypy narrows the return type. Same fail-closed semantics; cleaner type contract.
- **Files modified:** src/reconcile/sweeper.py
- **Commit:** 703b2a5

## Verification Evidence

- `uv run --python 3.13 pytest tests/test_reconcile.py -q` — 7 passed in 1.12s
- `uv run --python 3.13 pytest tests/test_reconcile.py tests/test_order_ids.py tests/test_approval_replay.py tests/test_adapter_strictness.py` — 46 passed, 0 regressions
- `uv run --python 3.13 pytest tests/test_paper_parity.py tests/test_paper_notify.py tests/test_paper_freeze.py tests/test_paper_resync.py tests/test_risk_parity.py` — 28 passed
- `uv run --python 3.13 pytest tests/test_backtest_simulator.py tests/test_backtest_binding.py tests/test_backtest_report.py tests/test_risk_portfolio.py tests/test_risk_quantization.py` — 90 passed
- `uv run --python 3.13 pytest tests/test_registry.py tests/test_quality_gates.py tests/test_metadata.py tests/test_core_tracer.py` — 45 passed
- `uv run --python 3.13 ruff check src/reconcile/ src/adapters/binance_usdm.py tests/test_reconcile.py` — All checks passed
- `uv run --python 3.13 mypy src/reconcile/ src/adapters/binance_usdm.py` — Success: no issues found
- Purity grep: zero forbidden imports (binance_sdk, sqlalchemy, pydantic, polars) in `src/reconcile/`

## Threat Model Coverage

| Threat ID | Category | Mitigation | Status |
|-----------|----------|------------|--------|
| T-8-30 | Tampering (wrong-leg cancel) | Authoritative position-zero verification (2 consecutive zero reads); pre/post journal images; re-scan after sweep (D-03) | Implemented + tested (Beh. 2, 5) |
| T-8-31 | Denial of service (divergence without SAFE_MODE) | Any divergence enters SAFE_MODE; entries blocked with RECONCILIATION_REQUIRED; monitoring + reconciliation continue | Implemented + tested (Beh. 3) |
| T-8-32 | Repudiation (ambiguous cancel response) | Query-by-client/algo-ID before retry; bounded batches (3 attempts, 30s); already-canceled-as-success; never blind retry (EXECUTION_SPEC 10) | Implemented + tested (adapter methods + sweep flow) |
| T-8-33 | Tampering (stale WS-only truth) | REST tick authoritative; WS ALGO_UPDATE/ORDER_TRADE_UPDATE are hints only (documented in safe_mode.py module docstring) | Implemented (REST-driven compare + sweep; documented posture) |
| T-8-SC | Tampering (locked SDK 17.4.0 only, no new installs) | Changelog diff in module docstring; legitimacy audit in RESEARCH covers the SDK; zero new package installs in this plan | Accepted (no new packages) |

## Next Steps

- Plan 08-05: Drills — end-to-end approval flow with Telegram fakes (the final plan in the phase)
- Phase 9 (live rollout): wire the reconciler tick into the main loop, add real-position verification against `position_information_v3`, schedule the SAFE_MODE tick at `SAFE_MODE_TICK_SECONDS`

## Self-Check: PASSED

- [x] src/reconcile/__init__.py exists
- [x] src/reconcile/compare.py exists
- [x] src/reconcile/sweeper.py exists
- [x] src/reconcile/safe_mode.py exists
- [x] tests/test_reconcile.py exists
- [x] tests/fixtures/phase8/orphan_divergence/input.json exists
- [x] tests/fixtures/phase8/orphan_divergence/expected.json exists
- [x] Commit a02aa45 exists (adapter truth surface)
- [x] Commit 703b2a5 exists (compare + sweeper + tests)
- [x] Commit 6fef291 exists (safe-mode tick + public surface polish)
- [x] 7 tests pass
- [x] Full suite sample (209 tests across 9 files): 209 passed, 0 regressions
- [x] Ruff check clean across new modules + extended adapter
- [x] Mypy strict clean across new modules + extended adapter
- [x] Purity grep clean (no binance_sdk / sqlalchemy / pydantic / polars in src/reconcile/)
- [x] Static guards pass (no place-order path, no SDK import in src/reconcile/)
- [x] SDK 17.3.1 → 17.4.0 delta documented in adapter docstring (RESEARCH Open Question 2 closed)
