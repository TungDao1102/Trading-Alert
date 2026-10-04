---
status: partial
phase: 09-live-execution-rollout
source: [09-01-SUMMARY.md, 09-02-SUMMARY.md, 09-03-SUMMARY.md, 09-04-SUMMARY.md]
started: 2026-10-04T00:00:00Z
updated: 2026-10-04T00:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Approved plan to LIMIT entry plus SL leg through the execution manager (09-01)
expected: Approved plan places exactly one entry and one SL leg on a fake adapter; stale plan and risk NO_TRADE yield zero adapter calls; ambiguous response queries before retry; core has no SDK imports or float math.
result: pass
verified: `uv run pytest tests/test_execution_*.py` (incl. test_execution_manager.py) all passed, exit 0, on 2026-10-04 with TEST_DATABASE_URL against PG17. Checked by Claude.

### 2. Adapter placement surface on SDK 17.x (09-01)
expected: Adapter exposes place_entry, place_algo_protective, query_order_by_client, cancel_normal_order, cancel_algo_order; SDK pinned >=17.3,<18.
result: pass
verified: Defined in src/adapters/binance_usdm.py (lines 1049, 1112, 1174, 1241, 1343); pyproject.toml pins binance-sdk-derivatives-trading-usds-futures>=17.3,<18; test_execution_adapter_contract.py passed. Checked by Claude (code inspection plus tests).

### 3. Protective legs sized to actual filled quantity, mode-correct (09-02 D1)
expected: One-way and hedge parameters correct; partial fills size all legs to filled qty; sub-minimum fill fails closed.
result: pass
source: automated
coverage_id: D1
verified: tests/test_execution_modes.py (4 referenced tests) pass; suite run green.

### 4. fold_fills is idempotent and deterministic (09-02 D2)
expected: Out-of-order and replayed fills fold to the same single view; entry without protective flags divergence.
result: pass
source: automated
coverage_id: D2
verified: tests/test_execution_partials.py (4 referenced tests) pass; suite run green.

### 5. Execution core purity (09-02 D3)
expected: No float(), no SDK/SQLAlchemy/Pydantic/Polars imports in core.
result: pass
source: automated
coverage_id: D3
verified: purity tests in test_execution_modes.py and test_execution_partials.py pass.

### 6. Placement gates fixed order, first-failure-wins (09-03 D1)
expected: Headroom, DAILY_STOP, stale, uncertain, portfolio gates evaluated in fixed order with zero place calls on rejection.
result: pass
source: automated
coverage_id: D1
verified: tests/test_execution_gates.py (5 referenced tests) pass.

### 7. LIVE_ORDERS_DISABLED default blocks all placement (09-03 D2)
expected: Default-disabled flag blocks placement with zero adapter calls until explicit operator enable.
result: pass
source: automated
coverage_id: D2
verified: test_disabled_flag_blocks_placement_with_zero_adapter_calls passes; test_execution_enablement.py green. Also confirmed by code: execute_approved_plan has no runtime caller in src beyond manager.py.

### 8. Manager wiring enablement -> gates -> risk -> placement (09-03 D3)
expected: Happy path places one entry and one SL; stale plan and risk NO_TRADE produce no adapter calls with preserved reason code.
result: pass
source: automated
coverage_id: D3
verified: tests/test_execution_manager.py (3 referenced tests) pass.

### 9. Ten fail-closed health probes (09-04 D1)
expected: Any FAIL probe blocks enablement; each probe journals one HEALTH_CHECK event.
result: pass
source: automated
coverage_id: D1
verified: tests/test_execution_health.py (3 referenced tests) pass.

### 10. Protective confirmation and multi-leg attach (09-04 D2)
expected: Unconfirmed SL leg yields ENTRY_WITHOUT_PROTECTIVE with zero rescue placement; partial replayed fills attach once.
result: pass
source: automated
coverage_id: D2
verified: tests/test_execution_attach.py (2 referenced tests) pass.

### 11. Live-5 symbol scope guard (09-04 D3)
expected: Non-live-5 symbols raise ValueError before any adapter call.
result: pass
source: automated
coverage_id: D3
verified: test_non_live5_symbol_raises_before_any_adapter_call passes.

### 12. Write-ahead and exactly-once order intent on PostgreSQL
expected: Order intent is written before the exchange call and applied exactly once.
result: pass
verified: test_execution_write_ahead_pg.py and test_execution_exactly_once_pg.py passed against PG17 in the green execution suite run; test_execution_emergency.py and test_execution_secret_posture.py also green.

### 13. Testnet rehearsal, credential provisioning, LIVE-TAP clearance (09-04 D4)
expected: Operator attestation with real evidence: testnet rehearsal order lifecycle, no-withdrawal keys with IP allowlist, health-green, LIVE-TAP cleared.
result: skipped
reason: Needs a real signed order on Binance demo/testnet; impossible now (no signed-request adapter, six exchange facts unconfirmed). Owned by Phases 24/25 per 09-VERIFICATION.md. Not fabricated.

## Summary

total: 13
passed: 12
issues: 0
pending: 0
skipped: 1
blocked: 0

## Gaps

[none]
